"""OS events for the Counsellor (P1 spec §3.9, R-45). When a plan changes, the kernel (and the replan code) write one
`os_event.v1` row into the `counsellor` outbox channel, in the same transaction as the change, template `os_event`,
key `os_event:{plan_id}:{kind}:{n}`. Only while the `counsellor` module is on and only for Counsellor plans. The host's
glue reads them here and turns each into one app notification; it is never a chat message. IDs and codes only."""

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import Connection, DateTime, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import clock, models, ports
from app.os.contracts.os_event import OsEventV1

CHANNEL = "counsellor"
TEMPLATE = "os_event"
_SOURCE = "counsellor"  # adapters.counsellor.manifest.NAME (not imported: the kernel imports this port)
KINDS = OsEventV1.model_fields["kind"].annotation.__args__


def emit(conn: Connection, tenant_id: str, plan_id: int, kind: str, n: int, at: datetime,
         instance_key: str | None = None) -> bool:
    """Writes the event row on `conn` (the caller's transaction). `n` is a number stable for this event (its
    `os_events` or proposal id), so the key is the same on a repeat and a repeat is skipped (invariant 8). Nothing is
    written when the module is off or the plan is not a Counsellor plan. True if a new row was written."""
    assert kind in KINDS, kind
    # Gate: Counsellor plans only. A self-serve plan has no Counsellor workspace to notify, so it emits nothing
    # (same rule as the escalation adapter).
    M, P, I, O = models.modules, models.plans, models.counsellor_intake, models.outbox
    if conn.execute(select(M.c.enabled).where(M.c.module == _SOURCE, M.c.tenant_id == tenant_id)).scalar() is not True:
        return False
    plan = conn.execute(select(P.c.source, P.c.student_ref).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).first()
    if plan is None or plan.source != _SOURCE:
        return False
    version = conn.execute(select(func.max(I.c.decision_version)).where(
        I.c.tenant_id == tenant_id, I.c.plan_id == plan_id)).scalar()
    key = f"{TEMPLATE}:{plan_id}:{kind}:{n}"
    payload = OsEventV1(key=key, student_ref=plan.student_ref, plan_id=plan_id, decision_version=version, kind=kind,
                        instance_key=instance_key, at=at).model_dump(mode="json", by_alias=True)
    return conn.execute(pg_insert(O).values(
        tenant_id=tenant_id, idempotency_key=key, channel=CHANNEL, recipient=plan.student_ref, template=TEMPLATE,
        payload=payload).on_conflict_do_nothing(constraint="uq_os_outbox_key").returning(O.c.id)
    ).scalar_one_or_none() is not None


def pending_events(limit: int = 100) -> list[OsEventV1]:
    """Events waiting for the glue to turn them into notifications, oldest first."""
    svc = ports.services()
    O = models.outbox
    with svc.engine.connect() as conn:
        rows = conn.execute(select(O.c.payload).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.channel == CHANNEL, O.c.template == TEMPLATE,
            O.c.status == "pending").order_by(O.c.id).limit(limit)).scalars().all()
    return [OsEventV1.model_validate(p) for p in rows]


def skip_stale_events(max_age: timedelta) -> int:
    """Marks every pending event row older than `max_age` as skipped, in one statement (the same status a refused
    delivery gets), so a backlog of old rows never hides a fresh one behind the page limit. Returns the count."""
    svc = ports.services()
    O = models.outbox
    cutoff = clock.now() - max_age
    with svc.engine.begin() as conn:
        return conn.execute(update(O).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.channel == CHANNEL, O.c.template == TEMPLATE,
            O.c.status == "pending", cast(O.c.payload["at"].astext, DateTime(timezone=True)) < cutoff)
            .values(status="skipped", sent_at=func.now(), attempts=O.c.attempts + 1)).rowcount


def mark_event_delivery(key: str, status: Literal["sent", "refused"]) -> None:
    """Records the glue's answer on the outbox row: `sent`, or `skipped` when the Counsellor cannot take it."""
    svc = ports.services()
    O = models.outbox
    with svc.engine.begin() as conn:
        conn.execute(update(O).where(O.c.tenant_id == svc.settings.tenant_id, O.c.channel == CHANNEL,
                                     O.c.template == TEMPLATE, O.c.idempotency_key == key)
                     .values(status="sent" if status == "sent" else "skipped", sent_at=func.now(),
                             attempts=O.c.attempts + 1))
