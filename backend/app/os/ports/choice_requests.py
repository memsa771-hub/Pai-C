"""Choice requests for the Counsellor (P1-T6, R-07). On a Counsellor plan PAI OS never changes the student's choice
itself: a choice change the student accepts (or makes in the route builder) becomes one `choice_request.v1` row in the
`counsellor` outbox channel, template `choice_request`, key `choice_request:{proposal_id}`, written in the same OS
transaction as the proposal's new status `requested`. The host's glue reads the rows here and hands each to the
decision service. IDs and codes only.

The OS cannot read host flags and the worker has no host, so the gate is configured by the host: `enabled()` says
whether the host part is on, `on_request(key)` is the post-commit hook (a nudge only; the host's sweep is the
backup). An unconfigured port reads as off, and then every path takes today's behaviour."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models, ports
from app.os.contracts.choice_request import ChoiceRequestV1
from app.os.contracts.route_contract import ProgrammeChoice

log = logging.getLogger("app.os.ports.choice_requests")

CHANNEL = "counsellor"
TEMPLATE = "choice_request"
_SOURCE = "counsellor"  # adapters.counsellor.manifest.NAME (not imported: the replan code imports this port)

_enabled: Callable[[], bool] | None = None
_on_request: Callable[[str], None] | None = None


def configure(enabled: Callable[[], bool] | None, on_request: Callable[[str], None] | None) -> None:
    global _enabled, _on_request
    _enabled, _on_request = enabled, on_request


def enabled() -> bool:
    """True only when the host configured the port and its part is on. Any exception reads as off."""
    if _enabled is None:
        return False
    try:
        return bool(_enabled())
    except Exception:
        return False


def key_of(proposal_id: int) -> str:
    return f"{TEMPLATE}:{proposal_id}"


def applies(conn: Connection, tenant_id: str, plan_id: int) -> bool:
    """Whether a choice change on this plan goes to the Counsellor: the host part is on, the `counsellor` module is
    on, and the plan is a Counsellor plan."""
    if not enabled():
        return False
    M, P = models.modules, models.plans
    if conn.execute(select(M.c.enabled).where(M.c.module == _SOURCE, M.c.tenant_id == tenant_id)).scalar() is not True:
        return False
    return conn.execute(select(P.c.source).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).scalar() == _SOURCE


def decision_version_of(conn: Connection, tenant_id: str, plan_id: int) -> int | None:
    """The newest decision version applied to a Counsellor plan (None for any other plan, or before the first)."""
    P, I = models.plans, models.counsellor_intake
    if conn.execute(select(P.c.source).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).scalar() != _SOURCE:
        return None
    return conn.execute(select(func.max(I.c.decision_version)).where(
        I.c.tenant_id == tenant_id, I.c.plan_id == plan_id)).scalar()


def emit(conn: Connection, tenant_id: str, plan_id: int, proposal_id: int, base_version: int,
         programmes: Sequence[ProgrammeChoice], at: datetime) -> bool:
    """Writes the request row on `conn` (the caller's transaction). The key is the same on a repeat, so a repeat is
    skipped. True if a new row was written."""
    P, O = models.plans, models.outbox
    plan = conn.execute(select(P.c.external_ref, P.c.student_ref).where(
        P.c.id == plan_id, P.c.tenant_id == tenant_id)).one()
    key = key_of(proposal_id)
    journey_id = plan.external_ref.rsplit(":", 2)[0]  # `{journey_id}:{destination}:{level}` (S8-D8)
    payload = ChoiceRequestV1(key=key, student_ref=plan.student_ref, journey_id=journey_id, proposal_id=proposal_id,
                              based_on_version=base_version, programmes=list(programmes), requested_at=at
                              ).model_dump(mode="json", by_alias=True)
    return conn.execute(pg_insert(O).values(
        tenant_id=tenant_id, idempotency_key=key, channel=CHANNEL, recipient=plan.student_ref, template=TEMPLATE,
        payload=payload).on_conflict_do_nothing(constraint="uq_os_outbox_key").returning(O.c.id)
    ).scalar_one_or_none() is not None


def pending(limit: int = 100) -> list[ChoiceRequestV1]:
    """Requests waiting for the glue to hand them to the Counsellor, oldest first."""
    svc = ports.services()
    O = models.outbox
    with svc.engine.connect() as conn:
        rows = conn.execute(select(O.c.payload).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.channel == CHANNEL, O.c.template == TEMPLATE,
            O.c.status == "pending").order_by(O.c.id).limit(limit)).scalars().all()
    return [ChoiceRequestV1.model_validate(p) for p in rows]


def notify(key: str) -> None:
    """The post-commit nudge. Never raises: the request is already stored and the host's sweep delivers it anyway."""
    if _on_request is None:
        return
    try:
        _on_request(key)
    except Exception as e:
        log.warning("choice request hook failed (%s)", type(e).__name__)
