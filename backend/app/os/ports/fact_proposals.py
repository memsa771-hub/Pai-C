"""Fact proposals for the Counsellor's Vault (P1-T7, D-y8, D-y9, R-16, row 6.7). When a student confirms a document, the
fields of its type that declare a `fact:` key (marks, GPA and scale, test scores) become one `fact_proposal.v1` row in
the `counsellor` outbox channel, template `fact_proposal`, written in its own OS transaction after the confirmation.
The host's glue reads the rows here and hands each to the Vault's sink; the Vault reconciler decides what is written.
Never a name, a date of birth, a passport value or any field without `fact:`. IDs, keys and the confirmed numbers only.

Gate: the confirmation runs only in the API, where the host configured the port, so `confirm_document` emits only
while `document_files.enabled()` holds. `pending`, `mark` and `backfill` take no gate: the host's sweep calls them only
while its part is on, and the OS holds no host flag (the worker never configures `enabled()`). `notify(key)` is the post-commit nudge; the sweep is the backup."""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import Connection, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models, ports
from app.os.contracts.fact_proposal import FactProposalV1

log = logging.getLogger("app.os.ports.fact_proposals")

CHANNEL = "counsellor"
TEMPLATE = "fact_proposal"
BACKFILL_INTAKE = ("planned", "revised", "replaced", "paused")  # a Counsellor decision that reached a plan
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MAX_TEXT = 200
OUTCOMES = {"written": "sent", "duplicate": "sent", "refused": "skipped", "invalid": "skipped",
            "superseded": "skipped"}
MAX_ATTEMPTS = 5  # failed deliveries before a row is set aside as `failed` (it must not starve newer rows)

_on_proposal: Callable[[str], None] | None = None


def configure(on_proposal: Callable[[str], None] | None = None) -> None:
    global _on_proposal
    _on_proposal = on_proposal


def key_of(doc_id: int, confirmed_at: datetime) -> str:
    """From the STORED confirmation time, never "now": a retry makes the same key, a new confirmation a new one."""
    return f"{TEMPLATE}:{doc_id}:{(confirmed_at - _EPOCH) // timedelta(microseconds=1)}"


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def facts_of(doc, types: Mapping, values: Mapping) -> list[dict]:
    """`[{key, value}]` for the type's fields that declare `fact:` and whose confirmed value is a non-empty number or
    short text. A field without `fact:` is never listed, whatever its value."""
    t = types.get(doc.doc_type)
    if t is None:
        return []
    out, seen = [], set()
    for f in t.fields:
        v = values.get(f.name)
        if f.fact is None or f.fact in seen or _empty(v) or isinstance(v, bool):
            continue
        if isinstance(v, str):
            v = v.strip()
            if len(v) > _MAX_TEXT:
                continue
        elif not isinstance(v, (int, float)):
            continue
        seen.add(f.fact)
        out.append({"key": f.fact, "value": v})
    return out[:20]


def emit(conn: Connection, tenant_id: str, doc, facts: list[dict]) -> str | None:
    """Writes the proposal row on `conn` for the document's stored confirmation. Returns its key when a new row was
    written; None when there are no facts, the document is not confirmed, or the row already exists (a retry)."""
    if not facts or doc.confirmed_at is None:
        return None
    key = key_of(doc.id, doc.confirmed_at)
    payload = FactProposalV1(key=key, student_ref=doc.student_ref, document_ref=doc.file_ref or f"os:{doc.id}",
                             doc_type=doc.doc_type, confirmed_at=doc.confirmed_at, facts=facts
                             ).model_dump(mode="json", by_alias=True)
    O = models.outbox
    written = conn.execute(pg_insert(O).values(
        tenant_id=tenant_id, idempotency_key=key, channel=CHANNEL, recipient=doc.student_ref, template=TEMPLATE,
        payload=payload).on_conflict_do_nothing(constraint="uq_os_outbox_key").returning(O.c.id)).scalar_one_or_none()
    return key if written is not None else None


def _doc_of(key: str) -> str:
    return key.split(":")[1] if key.count(":") >= 2 else key


def pending(limit: int = 100) -> list[FactProposalV1]:
    """Proposals waiting for the glue, oldest first. Of several pending proposals for one document only the newest is
    returned: the older ones are set aside as `superseded`, so the student is never asked to choose between their own
    two confirmations. A row that is not a valid proposal is set aside too (`skipped`)."""
    svc = ports.services()
    O = models.outbox
    where = (O.c.tenant_id == svc.settings.tenant_id, O.c.channel == CHANNEL, O.c.template == TEMPLATE,
             O.c.status == "pending")
    with svc.engine.connect() as conn:
        everyone = conn.execute(select(O.c.id, O.c.idempotency_key).where(*where).order_by(O.c.id)).all()
    newest: dict[str, int] = {}
    for row_id, key in everyone:
        newest[_doc_of(key)] = row_id
    for row_id, key in everyone:
        if newest[_doc_of(key)] != row_id:
            mark(key, "superseded")
    keep = [i for i, k in everyone if newest[_doc_of(k)] == i][:limit]
    if not keep:
        return []
    with svc.engine.connect() as conn:
        rows = conn.execute(select(O.c.idempotency_key, O.c.payload).where(*where, O.c.id.in_(keep))
                            .order_by(O.c.id)).all()
    out = []
    for key, payload in rows:
        try:
            out.append(FactProposalV1.model_validate({k: v for k, v in payload.items() if k != "outcome"}))
        except ValidationError:
            log.error("fact proposal row is not valid")
            mark(key, "invalid")
    return out


def record_failure(key: str) -> int:
    """Counts one failed delivery. After MAX_ATTEMPTS the row is set to `failed` (payload.outcome `failed`) so it
    stops being picked up. Returns the count."""
    svc = ports.services()
    O = models.outbox
    with svc.engine.begin() as conn:
        row = conn.execute(select(O.c.attempts, O.c.payload).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.idempotency_key == key, O.c.channel == CHANNEL,
            O.c.template == TEMPLATE, O.c.status == "pending").with_for_update()).first()
        if row is None:
            return 0
        attempts = row.attempts + 1
        values = {"attempts": attempts}
        if attempts >= MAX_ATTEMPTS:
            values.update(status="failed", payload={**row.payload, "outcome": "failed"})
        conn.execute(update(O).where(O.c.tenant_id == svc.settings.tenant_id, O.c.idempotency_key == key)
                     .values(**values))
    if attempts >= MAX_ATTEMPTS:
        log.error("fact proposal set aside after %d failed deliveries", attempts)
    return attempts


def mark(key: str, outcome: str) -> None:
    """Records the Vault's answer: `written` / `duplicate` -> sent; `refused` (the code stays in `payload.outcome`)
    -> skipped. Safe to repeat."""
    status = OUTCOMES.get(outcome.split(":", 1)[0])
    if status is None:
        raise ValueError("unknown outcome")
    svc = ports.services()
    O = models.outbox
    with svc.engine.begin() as conn:
        payload = conn.execute(select(O.c.payload).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.idempotency_key == key, O.c.channel == CHANNEL,
            O.c.template == TEMPLATE).with_for_update()).scalar_one_or_none()
        if payload is None:
            return
        conn.execute(update(O).where(O.c.tenant_id == svc.settings.tenant_id, O.c.idempotency_key == key)
                     .values(status=status, sent_at=func.now(), attempts=O.c.attempts + 1,
                             payload={**payload, "outcome": outcome}))


def notify(key: str | None) -> None:
    """The post-commit nudge. Never raises: the row is stored and the host's sweep delivers it anyway."""
    if key is None or _on_proposal is None:
        return
    try:
        _on_proposal(key)
    except Exception as e:  # class name only: no ids, no values
        log.warning("fact proposal hook failed (%s)", type(e).__name__)


def backfill(limit: int = 100) -> int:
    """Emits for confirmed documents of students with a Counsellor decision that reached a plan and no proposal row yet
    (a crash between the confirmation and the emit, or a document confirmed before the part was on). Returns how many
    rows were written. Repeating it writes nothing new."""
    from app.os.documents.store import DocumentStore

    svc = ports.services()
    tenant = svc.settings.tenant_id
    D, O, I = models.documents, models.outbox, models.counsellor_intake
    with_facts = [k for k, t in svc.document_types.items() if any(f.fact for f in t.fields)]
    if not with_facts:
        return 0
    with svc.engine.connect() as conn:
        due = conn.execute(select(D.c.id, D.c.confirmed_at).where(
            D.c.tenant_id == tenant, D.c.status == "confirmed", D.c.doc_type.in_(with_facts),
            D.c.confirmed_at.is_not(None),
            exists().where(I.c.tenant_id == tenant, I.c.student_ref == D.c.student_ref,
                           I.c.status.in_(BACKFILL_INTAKE))).order_by(D.c.id)).all()
        held = set(conn.execute(select(O.c.idempotency_key).where(
            O.c.tenant_id == tenant, O.c.channel == CHANNEL, O.c.template == TEMPLATE)).scalars())
    # the document's CURRENT key: a failed emit of a re-confirmation is recovered even when an older one is on file
    ids = [doc_id for doc_id, at in due if key_of(doc_id, at) not in held]
    store, written = DocumentStore(svc.engine, tenant), 0
    for doc_id in ids:
        if written >= limit:
            break
        doc = store.get(doc_id)
        if doc is None or doc.status != "confirmed":
            continue
        values = {f["field"]: f["value_confirmed"] for f in store.fields(doc_id)}
        facts = facts_of(doc, svc.document_types, values)
        with svc.engine.begin() as conn:
            if emit(conn, tenant, doc, facts) is not None:
                written += 1
    return written
