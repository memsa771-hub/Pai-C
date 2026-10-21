"""The document workflow `os.document` and its enqueue (Slice 3 spec §2, S3-D5, S3-D7, S3-D8, S3-D11, §6).

One workflow per upload: its ID holds the document and the file's SHA-256, so enqueueing the same upload again
returns the same workflow. The API enqueues it through DBOSClient. Over the month's cap, the workflow ends and the
document stays `uploaded` (a sleeping workflow would hold a slot of the shared queue); a daily job enqueues the
waiting uploads again, with the day in the workflow ID. The `start` step claims the document (`uploaded` to
`reading`) in one statement, so a document is still read once. Every side effect
is a DBOS step (the budget check, the agent-run row, the fields, the findings, the status), and the reading runs at
workflow level, so each model request is its own step (DBOSDurability). Step retries are the only retries
(invariant 7), and every write is idempotent (invariant 8): agent runs by (document, reading), fields by
(document, field), and the open findings are replaced as a whole.

The file and its page images never go into a step's output: DBOS keeps step outputs, and deleting a document must
remove its content (S3-D10). The `prepare` step only checks that the file opens; the pages are prepared again,
deterministically, at workflow level just before the reading.
"""

import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import Engine, func, insert, select, update

from app.os import models
from app.os.agents.spec import AgentSpec
from app.os.documents.checks import Finding, cross_check
from app.os.documents.intake import UploadError, check_upload, prepare
from app.os.documents.reader import read_document
from app.os.documents.store import Document, DocumentStore, FindingStore
from app.os.documents.types import DocumentType
from app.os.documents.validators import validate
from app.os.knowledge.research.readings import AgentRuns, cost
from app.os.settings import OsSettings

DOCUMENT_WORKFLOW = "os.document"
READ_FAILED = "We could not read this document. Please try again."
COMPARED = ("read", "needs_student", "confirmed")  # documents whose fields take part in cross-checks
D = models.documents


def document_workflow_id(tenant_id: str, document_id: int, sha256: str, retry_day: date | None = None) -> str:
    wid = f"document:{tenant_id}:{document_id}:{sha256[:16]}"
    return wid if retry_day is None else f"{wid}:{retry_day.isoformat()}"


def enqueue_document(client: DBOSClient, tenant_id: str, doc: Document, retry_day: date | None = None) -> str:
    """Starts the reading of one upload. Enqueueing the same workflow ID again returns the existing workflow.
    `retry_day` is for uploads that waited for the budget (`retry_waiting`)."""
    from app.os.runner.workflow import APP_VERSION, QUEUE_NAME  # imported here: the runner imports documents

    wid = document_workflow_id(tenant_id, doc.id, doc.sha256, retry_day)
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": DOCUMENT_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options, doc.id)
    return wid


def retry_waiting(engine: Engine, client: DBOSClient, tenant_id: str, today: date) -> int:
    """Enqueues every upload still `uploaded` (it waited for the budget, or its first enqueue was lost) once for
    `today`. Returns how many were sent. The daily `documents_retry` job calls it."""
    with engine.connect() as conn:
        ids = conn.execute(select(D.c.id).where(D.c.tenant_id == tenant_id, D.c.status == "uploaded")
                           .order_by(D.c.id)).scalars().all()
    store = DocumentStore(engine, tenant_id)
    for doc_id in ids:
        enqueue_document(client, tenant_id, store.get(doc_id), retry_day=today)
    return len(ids)


class student_lock:
    """One student's cross-checks run one at a time (a Postgres advisory lock held for the block)."""

    def __init__(self, engine: Engine, tenant_id: str, student_ref: str) -> None:
        self.engine, self.name = engine, f"os.documents:{tenant_id}:{student_ref}"

    def __enter__(self) -> None:
        self.conn = self.engine.connect()
        self.key = self.conn.execute(select(func.hashtextextended(self.name, 0))).scalar()
        self.conn.execute(select(func.pg_advisory_lock(self.key)))

    def __exit__(self, *exc) -> None:
        try:
            self.conn.execute(select(func.pg_advisory_unlock(self.key)))
            self.conn.commit()
        finally:
            self.conn.close()


def _resolved(engine: Engine, tenant_id: str, student_ref: str) -> set[tuple]:
    FI = models.document_findings
    with engine.connect() as conn:
        rows = conn.execute(select(FI.c.kind, FI.c.field, FI.c["items"]).where(
            FI.c.tenant_id == tenant_id, FI.c.student_ref == student_ref, FI.c.status == "resolved")).all()
    return {(r.kind, r.field, tuple(tuple(i) for i in r.items)) for r in rows}


def compare_documents(engine: Engine, tenant_id: str, student_ref: str, types: Mapping[str, DocumentType],
                      variants: list[set[str]], include_id: int | None = None) -> list[Finding]:
    """Replaces the student's open findings with a cross-check of their read documents (plus `include_id`, the
    one being read). A confirmed field is compared by its confirmed value. A finding the student already resolved
    (the same documents and values) is not opened again. Returns the open findings. One student at a time
    (`student_lock`), so overlapping checks cannot lose or duplicate findings."""
    with student_lock(engine, tenant_id, student_ref):
        docs = DocumentStore(engine, tenant_id)
        items = []
        for d in docs.list_for(student_ref):
            if (d.id != include_id and d.status not in COMPARED) or d.doc_type not in types:
                continue
            values = {f["field"]: f["value_confirmed"] if f["confirmed_at"] else f["value_read"]
                      for f in docs.fields(d.id)}
            items.append((d.id, types[d.doc_type], values))
        resolved = _resolved(engine, tenant_id, student_ref)
        found = [f for f in cross_check(items, variants)
                 if (f.kind, f.field, tuple(tuple(i) for i in f.items)) not in resolved]
        FindingStore(engine, tenant_id).replace_open(
            student_ref, [{"kind": f.kind, "field": f.field, "items": f.items} for f in found])
        return found


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", s.casefold()).split())


def type_matches(t: DocumentType, detected: str | None) -> bool:
    """Whether the reader's `detected_type` (free text) names the type the student chose: its key or label, either
    way round as whole words. No answer is not a mismatch."""
    if not detected or not detected.strip():
        return True
    d = f" {_norm(detected)} "
    return any(f" {n} " in d or d in f" {n} " for n in (_norm(t.key), _norm(t.label)))


def register_documents(engine: Engine, settings: OsSettings, readers: Mapping[str, object], spec: AgentSpec,
                       types: Mapping[str, DocumentType], variants: list[set[str]],
                       clock: Callable[[], datetime] = _utcnow) -> None:
    """Registers os.document and its steps. Must run before DBOS.launch(), with the readers built once per process
    (reader.build_readers)."""
    from app.os.runner.workflow import STEP_CONFIG  # imported here: the runner imports documents

    tenant = settings.tenant_id
    docs, runs = DocumentStore(engine, tenant), AgentRuns(engine, tenant)

    def start(document_id: int) -> dict:
        """`reading` (claimed by this workflow), `budget` when the month's cap is spent (a budget_exceeded event;
        the document stays `uploaded`), or `skipped` when the document is not ours to read (deleted, or claimed or
        read by another workflow). A replay after a crash inside this step finds its own claim and carries on."""
        wid = DBOS.workflow_id
        with engine.connect() as conn:
            row = conn.execute(select(D.c.status, D.c.claimed_by, D.c.doc_type, D.c.student_ref).where(
                D.c.id == document_id, D.c.tenant_id == tenant)).first()
        if row is not None and row.status == "reading" and row.claimed_by == wid:
            return {"status": "reading", "doc_type": row.doc_type, "student_ref": row.student_ref}
        doc = docs.get(document_id)
        if doc is None or doc.status != "uploaded":
            return {"status": "skipped"}
        if doc.doc_type not in types or doc.doc_type not in readers:
            docs.set_status(document_id, "failed", error="This document type is not supported.")
            return {"status": "skipped"}
        now = clock()
        spent = runs.month_spend(now, spec.id)
        if spent >= settings.documents_monthly_usd:
            with engine.begin() as conn:
                conn.execute(insert(models.events).values(tenant_id=tenant, type="budget_exceeded", payload={
                    "tenant_id": tenant, "document_id": document_id, "agent": spec.id, "spent_usd": spent,
                    "cap_usd": settings.documents_monthly_usd}))
            return {"status": "budget"}
        with engine.begin() as conn:
            claimed = conn.execute(update(D).where(D.c.id == document_id, D.c.tenant_id == tenant,
                                                   D.c.status == "uploaded")
                                   .values(status="reading", error=None, claimed_by=wid).returning(D.c.id)).first()
        if claimed is None:
            return {"status": "skipped"}
        return {"status": "reading", "doc_type": doc.doc_type, "student_ref": doc.student_ref}

    def check_file(document_id: int) -> dict:
        """The file's kind and page count, or the reason it cannot be read (shown to the student)."""
        data = docs.file_bytes(document_id)
        try:
            kind = check_upload("The file", data)
            return {"kind": kind, "pages": len(prepare(data, kind))}
        except UploadError as e:
            return {"error": str(e)}

    def record(document_id: int, model: str, usage: dict, cost_usd: float, error: str | None) -> None:
        from pydantic_ai.usage import RunUsage

        runs.record(None, f"document:{document_id}", document_id=document_id, spec=spec, model=model,
                    usage=RunUsage(**usage), cost_usd=cost_usd, error=error)

    def check(doc_type: str, values: dict) -> dict:
        return validate(types[doc_type], values, clock().date())

    def store(document_id: int, values: dict, checks: dict) -> None:
        if docs.get(document_id).status != "deleted":  # deleted while it was being read: no fields come back
            docs.save_fields(document_id, values, checks)

    def compare(student_ref: str, document_id: int) -> int:
        """The student's findings again, after `finish`, so a document read at the same time sees this one."""
        return len(compare_documents(engine, tenant, student_ref, types, variants, include_id=document_id))

    def finish(document_id: int, status: str, error: str | None, detected_type: str | None,
               pages: int | None) -> None:
        if docs.get(document_id).status == "deleted":
            return  # deleted while it was being read: stays deleted
        docs.set_status(document_id, status, error=error, detected_type=detected_type, pages=pages)

    step = lambda name, fn: DBOS.step(name=f"os.document.{name}", **STEP_CONFIG)(fn)  # noqa: E731
    start_step, prepare_step, record_step = step("start", start), step("prepare", check_file), step("record", record)
    validate_step, store_step = step("validate", check), step("store", store)
    compare_step, finish_step = step("cross_check", compare), step("finish", finish)

    def document(document_id: int) -> dict:
        begun = start_step(document_id)
        if begun["status"] != "reading":  # over the month's cap: retry_waiting sends it again the next day
            return begun
        doc_type, student_ref = begun["doc_type"], begun["student_ref"]
        checked = prepare_step(document_id)
        if "error" in checked:
            finish_step(document_id, "failed", checked["error"], None, None)
            return {"status": "failed"}
        try:
            data = docs.file_bytes(document_id)
        except KeyError:  # deleted since the check
            return {"status": "skipped"}
        t = types[doc_type]
        reading = read_document(readers[doc_type], spec, t, prepare(data, checked["kind"]))
        usage = {"input_tokens": reading.usage.input_tokens or 0,
                 "cache_read_tokens": reading.usage.cache_read_tokens or 0,
                 "output_tokens": reading.usage.output_tokens or 0, "requests": reading.usage.requests or 0}
        error = None if reading.error is None else reading.error.split(":", 1)[0]  # the kind only: no values
        record_step(document_id, readers[doc_type].model.model_name, usage, cost(reading.usage, settings, spec.tier),
                    error)
        if reading.values is None:
            finish_step(document_id, "failed", READ_FAILED, None, checked["pages"])
            return {"status": "failed"}
        checks = validate_step(doc_type, reading.values)
        store_step(document_id, reading.values, checks)
        status = "read" if type_matches(t, reading.detected_type) else "needs_student"
        finish_step(document_id, status, None, reading.detected_type, checked["pages"])
        compare_step(student_ref, document_id)  # after finish: a document read at the same time sees this one
        return {"status": status}

    DBOS.workflow(name=DOCUMENT_WORKFLOW)(document)
