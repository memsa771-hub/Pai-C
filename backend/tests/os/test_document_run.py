"""Slice 3 Task 7: the os.document workflow (spec S3-D5, S3-D7, S3-D8, S3-D11, §6).

DBOS runs in this process (as in test_research_run). The readings come from a FunctionModel that answers per
document type, and every file is a synthetic image made here, so nothing leaves the machine and no real document
is used.
"""

import io
from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import insert, select, text, update

from app.os import models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.documents.checks import load_name_variants
from app.os.documents.reader import build_readers
from app.os.documents.run import document_workflow_id, enqueue_document, register_documents, retry_waiting
from app.os.documents.store import DocumentStore, FindingStore
from app.os.documents.types import load_document_types
from app.os.knowledge.research.readings import AgentRuns
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema

TENANT = "pai"
STUDENT = "student-1"
NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
TYPES = load_document_types()
SPEC = load_agent_spec(AGENT_DIR / "documents.v1.yaml")
RESEARCH_SPEC = load_agent_spec(AGENT_DIR / "research.v1.yaml")

# Fictional values only (no real-set value may appear here).
TRANSCRIPT = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Khan", "date_of_birth": "2001-04-12",
              "institution": "Example University", "cgpa": 3.7, "cgpa_scale": 4.0, "issue_date": "31/02/2024",
              "detected_type": "transcript"}
DEGREE = {"student_name": "Sara Ahmad Khan", "father_name": "Ahmed Khan", "detected_type": "degree certificate"}


def jpeg(seed: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (600, 800), (seed % 256, 200, 200)).save(out, "JPEG")
    return out.getvalue()


class Ctx:
    def __init__(self, engine, client):
        self.engine, self.client = engine, client
        self.answers: dict[str, dict] = {"transcript": TRANSCRIPT, "degree_certificate": DEGREE}
        self.calls: list[str] = []
        self.docs = DocumentStore(engine, TENANT)

    def upload(self, doc_type: str, seed: int, student: str = STUDENT) -> int:
        t = TYPES[doc_type]
        return self.docs.create(student, doc_type, t.version, f"{doc_type}.jpg", "image/jpeg", jpeg(seed))

    def read(self, doc_id: int, timeout: float = 30):
        wid = enqueue_document(self.client, TENANT, self.docs.get(doc_id))
        return self.client.retrieve_workflow(wid).get_result()


def _type_of(messages) -> str:
    system = " ".join(p.content for m in messages for p in m.parts if p.part_kind == "system-prompt")
    return next(k for k, t in TYPES.items() if f"expected to be a {t.label}," in system)


def make_documents(engine, os_db, settings_env: dict | None = None, clock=lambda: NOW):
    from dbos import DBOS, DBOSClient

    from app.os.kernel import Kernel
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
                              **(settings_env or {})})
    holder: dict = {}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        ctx: Ctx = holder["ctx"]
        key = _type_of(messages)
        ctx.calls.append(key)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, ctx.answers.get(key, {}))])

    readers = build_readers(FunctionModel(fn), TYPES, SPEC)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, TENANT))
    register_documents(engine, settings, readers, SPEC, TYPES, load_name_variants(), clock=clock)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    ctx = Ctx(engine, client)
    holder["ctx"] = ctx
    return ctx


def stop(ctx: Ctx) -> None:
    from dbos import DBOS

    ctx.client.destroy()
    DBOS.destroy(destroy_registry=True)


@pytest.fixture
def documents(os_db, engine, clean):
    ctx = make_documents(engine, os_db)
    try:
        yield ctx
    finally:
        stop(ctx)


def agent_rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(models.agent_runs).order_by(models.agent_runs.c.id)).all()


def events(engine, kind):
    with engine.connect() as conn:
        return conn.execute(select(models.events.c.payload).where(models.events.c.type == kind)
                            .order_by(models.events.c.id)).scalars().all()


# --- AgentRuns: the document path and spend per agent (handoff §6, Task 7 gaps) --------------------------------


def test_agent_runs_records_a_document_reading_once(engine, clean):
    doc_id = DocumentStore(engine, TENANT).create(STUDENT, "transcript", 1, "t.jpg", "image/jpeg", jpeg(1))
    runs = AgentRuns(engine, TENANT)
    usage = RunUsage(input_tokens=900, output_tokens=80, requests=1)
    assert runs.record(None, f"document:{doc_id}", document_id=doc_id, spec=SPEC, model="m", usage=usage,
                       cost_usd=0.002) is True
    assert runs.record(None, f"document:{doc_id}", document_id=doc_id, spec=SPEC, model="m", usage=usage,
                       cost_usd=0.002) is False
    [row] = agent_rows(engine)
    assert (row.document_id, row.research_run_id, row.reading, row.agent) == \
        (doc_id, None, f"document:{doc_id}", "documents")


def test_month_spend_is_per_agent(engine, clean):
    doc_id = DocumentStore(engine, TENANT).create(STUDENT, "transcript", 1, "t.jpg", "image/jpeg", jpeg(1))
    with engine.begin() as conn:
        run_id = conn.execute(insert(models.research_runs).values(
            tenant_id=TENANT, programme_ref="x", intake_year=2027, workflow_id="w", status="done")
            .returning(models.research_runs.c.id)).scalar()
    runs = AgentRuns(engine, TENANT)
    runs.record(run_id, "A", spec=RESEARCH_SPEC, model="m", usage=None, cost_usd=3.0, at=NOW)
    runs.record(None, f"document:{doc_id}", document_id=doc_id, spec=SPEC, model="m", usage=None, cost_usd=0.04,
                at=NOW)
    assert runs.month_spend(NOW, "research") == pytest.approx(3.0)
    assert runs.month_spend(NOW, "documents") == pytest.approx(0.04)


def test_documents_budget_setting():
    assert load_settings({"OS_DATABASE_URL": "postgresql://unused/x"}).documents_monthly_usd == 10.0
    env = {"OS_DATABASE_URL": "postgresql://unused/x", "OS_DOCUMENTS_MONTHLY_USD": "2.5"}
    assert load_settings(env).documents_monthly_usd == 2.5


def test_worker_registers_documents_only_with_a_key():
    from app.os.runner import worker

    settings = load_settings({"OS_DATABASE_URL": "postgresql://unused/x"})
    assert worker.register_documents_if_configured(settings, engine=None) is False


def test_workflow_id_names_the_upload():
    assert document_workflow_id("pai", 7, "ab" * 32) == "document:pai:7:" + "ab" * 8
    assert document_workflow_id("pai", 7, "ab" * 32, date(2026, 11, 1)) == "document:pai:7:" + "ab" * 8 + ":2026-11-01"


# --- the workflow ----------------------------------------------------------------------------------------------


def test_upload_read_once(documents):
    doc_id = documents.upload("transcript", 1)
    doc = documents.docs.get(doc_id)
    wid = enqueue_document(documents.client, TENANT, doc)
    assert enqueue_document(documents.client, TENANT, doc) == wid  # the same upload: the same workflow
    documents.client.retrieve_workflow(wid).get_result()
    assert enqueue_document(documents.client, TENANT, doc) == wid
    documents.client.retrieve_workflow(wid).get_result()
    assert documents.calls == ["transcript"]
    [row] = agent_rows(documents.engine)
    assert (row.document_id, row.reading, row.agent, row.agent_version) == (doc_id, f"document:{doc_id}",
                                                                             "documents", 1)
    assert documents.docs.get(doc_id).status == "read"


def test_fields_and_checks_stored(documents):
    doc_id = documents.upload("transcript", 1)
    documents.read(doc_id)
    doc = documents.docs.get(doc_id)
    assert (doc.status, doc.detected_type, doc.pages, doc.error) == ("read", "transcript", 1, None)
    assert doc.read_at is not None
    fields = {f["field"]: f for f in documents.docs.fields(doc_id)}
    assert set(fields) == {f.name for f in TYPES["transcript"].fields}  # every field, missing ones too
    assert fields["student_name"]["value_read"] == "Sara Ahmed Khan" and fields["student_name"]["check"] == "ok"
    assert fields["cgpa"]["value_read"] == 3.7 and fields["cgpa"]["check"] == "ok"
    # a malformed date is kept as read and marked (Review Focus #5)
    assert fields["issue_date"]["value_read"] == "31/02/2024" and fields["issue_date"]["check"] == "check_failed"
    assert fields["serial_number"]["value_read"] is None and fields["serial_number"]["check"] == "missing"
    assert all(f["value_confirmed"] is None for f in fields.values())  # the student confirms later (invariant 4)


def test_type_mismatch_needs_student(documents):
    documents.answers["transcript"] = {**TRANSCRIPT, "detected_type": "IELTS Test Report Form"}
    doc_id = documents.upload("transcript", 1)
    documents.read(doc_id)
    doc = documents.docs.get(doc_id)
    assert (doc.status, doc.detected_type) == ("needs_student", "IELTS Test Report Form")
    assert documents.docs.fields(doc_id)  # still read and stored: never rejected silently (S3-D7)


def test_detected_type_by_label_is_not_a_mismatch(documents):
    doc_id = documents.upload("degree_certificate", 2)  # the reader says "degree certificate"
    documents.read(doc_id)
    assert documents.docs.get(doc_id).status == "read"


def test_findings_written_across_documents(documents):
    t_id = documents.upload("transcript", 1)
    documents.read(t_id)
    assert FindingStore(documents.engine, TENANT).list_open(STUDENT) == []  # one document: nothing to compare
    d_id = documents.upload("degree_certificate", 2)
    documents.read(d_id)
    [finding] = FindingStore(documents.engine, TENANT).list_open(STUDENT)
    assert (finding["kind"], finding["field"]) == ("variant", "full_name")  # Ahmed / Ahmad
    assert finding["items"] == [[t_id, "Sara Ahmed Khan"], [d_id, "Sara Ahmad Khan"]]
    # another student's documents are never compared with these
    other = documents.upload("degree_certificate", 3, student="student-2")
    documents.read(other)
    assert FindingStore(documents.engine, TENANT).list_open("student-2") == []
    assert len(FindingStore(documents.engine, TENANT).list_open(STUDENT)) == 1


def test_budget_exceeded_waits(os_db, engine, clean):
    """Over the month's cap the upload is not read and stays `uploaded`; the next day's retry reads it (spec §6)."""
    times = iter([datetime(2026, 10, 31, 23, 50, tzinfo=timezone.utc)])

    def clock():  # the first check is in October (spent); the retry is in November (a new month)
        return next(times, datetime(2026, 11, 1, 0, 10, tzinfo=timezone.utc))

    with engine.begin() as conn:  # this month's documents budget is spent
        doc0 = DocumentStore(engine, TENANT).create("someone", "transcript", 1, "x.jpg", "image/jpeg", jpeg(9))
        conn.execute(update(models.documents).where(models.documents.c.id == doc0).values(status="read"))
        conn.execute(insert(models.agent_runs).values(
            tenant_id=TENANT, document_id=doc0, reading=f"document:{doc0}", agent="documents", agent_version=1,
            model="m", cost_usd=10.0, at=datetime(2026, 10, 20, tzinfo=timezone.utc)))
    ctx = make_documents(engine, os_db, clock=clock)
    try:
        doc_id = ctx.upload("transcript", 1)
        assert ctx.read(doc_id) == {"status": "budget"}
        [event] = events(engine, "budget_exceeded")
        assert event["document_id"] == doc_id and event["cap_usd"] == 10.0 and event["spent_usd"] == 10.0
        assert ctx.calls == [] and ctx.docs.get(doc_id).status == "uploaded" and len(agent_rows(engine)) == 1
        assert retry_waiting(engine, ctx.client, TENANT, date(2026, 11, 1)) == 1  # the daily job
        doc = ctx.docs.get(doc_id)
        ctx.client.retrieve_workflow(document_workflow_id(TENANT, doc_id, doc.sha256, date(2026, 11, 1))).get_result()
        assert ctx.calls == ["transcript"] and ctx.docs.get(doc_id).status == "read"
        assert retry_waiting(engine, ctx.client, TENANT, date(2026, 11, 2)) == 0  # read: nothing waits
    finally:
        stop(ctx)


def test_research_spend_does_not_block_documents(os_db, engine, clean):
    with engine.begin() as conn:
        run_id = conn.execute(insert(models.research_runs).values(
            tenant_id=TENANT, programme_ref="x", intake_year=2027, workflow_id="w", status="done")
            .returning(models.research_runs.c.id)).scalar()
        conn.execute(insert(models.agent_runs).values(
            tenant_id=TENANT, research_run_id=run_id, reading="A", agent="research", agent_version=1, model="m",
            cost_usd=50.0, at=NOW - timedelta(days=1)))
    ctx = make_documents(engine, os_db)
    try:
        doc_id = ctx.upload("transcript", 1)
        assert ctx.read(doc_id) == {"status": "read"}
        assert events(engine, "budget_exceeded") == []
    finally:
        stop(ctx)


def test_second_workflow_does_not_read_again(documents):
    """A retry enqueued for an upload that its first workflow already read is skipped: one reading per document."""
    doc_id = documents.upload("transcript", 1)
    documents.read(doc_id)
    wid = enqueue_document(documents.client, TENANT, documents.docs.get(doc_id), retry_day=date(2026, 10, 22))
    assert documents.client.retrieve_workflow(wid).get_result() == {"status": "skipped"}
    assert documents.calls == ["transcript"] and len(agent_rows(documents.engine)) == 1


def test_model_requests_are_dbos_steps(documents):
    doc_id = documents.upload("transcript", 1)
    documents.read(doc_id)
    wid = document_workflow_id(TENANT, doc_id, documents.docs.get(doc_id).sha256)
    with documents.engine.connect() as conn:
        names = conn.execute(text(
            f"SELECT function_name FROM {TEST_DBOS_SCHEMA}.operation_outputs WHERE workflow_uuid = :w "
            "ORDER BY function_id"), {"w": wid}).scalars().all()
    assert sum("model.request" in n for n in names) == 1
    assert [n for n in names if n.startswith("os.document.")] == [
        "os.document.start", "os.document.prepare", "os.document.record", "os.document.validate",
        "os.document.store", "os.document.cross_check", "os.document.finish"]


def test_file_bytes_never_in_step_outputs(documents):
    """Deleting a document must remove its content (S3-D10): no step output holds the file or a page image."""
    doc_id = documents.upload("transcript", 1)
    documents.read(doc_id)
    wid = document_workflow_id(TENANT, doc_id, documents.docs.get(doc_id).sha256)
    with documents.engine.connect() as conn:
        sizes = conn.execute(text(
            f"SELECT function_name, length(coalesce(output, '')) FROM {TEST_DBOS_SCHEMA}.operation_outputs "
            "WHERE workflow_uuid = :w"), {"w": wid}).all()
    big = [(name, n) for name, n in sizes if n > 4000 and "model.request" not in name]
    assert big == []


def test_unreadable_file_fails_with_reason(documents):
    t = TYPES["transcript"]
    doc_id = documents.docs.create(STUDENT, "transcript", t.version, "t.jpg", "image/jpeg",
                                   b"\xff\xd8\xff" + b"not really a jpeg")
    documents.read(doc_id)
    doc = documents.docs.get(doc_id)
    assert doc.status == "failed" and "could not be read" in doc.error
    assert documents.calls == [] and agent_rows(documents.engine) == []


def test_reading_error_fails_and_is_recorded(documents):
    documents.answers["transcript"] = {"cgpa": "not a number"}  # invalid every time: repair gives up
    doc_id = documents.upload("transcript", 1)
    documents.read(doc_id)
    doc = documents.docs.get(doc_id)
    assert doc.status == "failed" and doc.error.startswith("We could not read this document")
    assert documents.calls == ["transcript"] * (SPEC.retries.output + 1)
    [row] = agent_rows(documents.engine)
    assert row.document_id == doc_id and row.error and "not a number" not in row.error  # no value in the error
    assert documents.docs.fields(doc_id) == []


def test_deleted_before_reading_is_skipped(documents):
    doc_id = documents.upload("transcript", 1)
    doc = documents.docs.get(doc_id)
    documents.docs.delete(doc_id)
    wid = enqueue_document(documents.client, TENANT, doc)
    assert documents.client.retrieve_workflow(wid).get_result()["status"] == "skipped"
    assert documents.calls == [] and documents.docs.get(doc_id).status == "deleted"


def test_claim_survives_a_crash_inside_start(documents):
    """A worker killed after the claim commits but before DBOS records the step replays `start`: the same workflow
    carries on (invariant 8), and the document is not left in `reading`."""
    doc_id = documents.upload("transcript", 1)
    doc = documents.docs.get(doc_id)
    wid = document_workflow_id(TENANT, doc_id, doc.sha256)
    with documents.engine.begin() as conn:  # what the first attempt of `start` left behind
        conn.execute(update(models.documents).where(models.documents.c.id == doc_id)
                     .values(status="reading", claimed_by=wid))
    assert documents.read(doc_id) == {"status": "read"}
    assert documents.calls == ["transcript"]


def test_a_document_claimed_by_another_workflow_is_skipped(documents):
    doc_id = documents.upload("transcript", 1)
    with documents.engine.begin() as conn:
        conn.execute(update(models.documents).where(models.documents.c.id == doc_id)
                     .values(status="reading", claimed_by="document:pai:other"))
    assert documents.read(doc_id) == {"status": "skipped"}
    assert documents.calls == [] and documents.docs.get(doc_id).status == "reading"
