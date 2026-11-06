"""The EscalationSink port (Slice 8 spec §2.2, S8-D12; promised by Slice 7 S7-D10). Every support case is opened
through it: the standalone adapter always writes the case, and the Counsellor adapter (Task 7) may also tell the
Counsellor. The glue reads the Counsellor's pending escalations here and marks each one delivered."""

from typing import Literal, Protocol

from sqlalchemy import func, select, update

from app.os import models, ports
from app.os.contracts.escalation_v2 import EscalationV2

_CHANNEL = "counsellor"  # adapters.counsellor.escalation.CHANNEL (not imported: the replan code imports this port)


class EscalationSink(Protocol):
    def escalate(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        """Opens (or reuses) the support case for these events and returns its id."""
        ...


def pending_counsellor_escalations(limit: int = 100) -> list[EscalationV2]:
    """Escalations waiting for the glue to hand them to the Counsellor, oldest first."""
    svc = ports.services()
    O = models.outbox
    with svc.engine.connect() as conn:
        rows = conn.execute(select(O.c.payload).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.channel == _CHANNEL, O.c.template == "escalation",
            O.c.status == "pending")  # not the `os_event` rows that share this channel (R-45)
            .order_by(O.c.id).limit(limit)).scalars().all()
    return [_v2(p) for p in rows]


def event_type_of(key: str) -> str | None:
    """The type of the event the escalation's support case was opened for (`escalation:{case_id}`), or None for an
    intake refusal (no case) and for any key that names no case. The frozen payload does not carry it."""
    if not key.startswith("escalation:") or key.startswith("escalation:intake:"):
        return None
    svc = ports.services()
    tenant, C, EV = svc.settings.tenant_id, models.support_cases, models.events
    with svc.engine.connect() as conn:
        event_ids = conn.execute(select(C.c.event_ids).where(
            C.c.tenant_id == tenant, C.c.id == int(key.split(":")[1]))).scalar()
        if not event_ids:
            return None
        return conn.execute(select(EV.c.type).where(EV.c.tenant_id == tenant, EV.c.id == event_ids[0])).scalar()


def _v2(payload: dict) -> EscalationV2:
    """A row stored before P1-T6 is an EscalationV1: it is read as v2 with no decision version."""
    if payload.get("schema") == "pai.escalation.v1":
        payload = {**payload, "schema": "pai.escalation.v2", "decision_version": None}
    return EscalationV2.model_validate(payload)


def mark_counsellor_delivery(key: str, status: Literal["sent", "refused"], reason: str | None = None) -> None:
    """Records the Counsellor's answer on the outbox row and on the support case (or the intake row). A refused
    escalation stays a support case, open, for a person in PAI OS (spec §2.5)."""
    from app.os.adapters.counsellor.store import IntakeStore

    if not key.startswith("escalation:"):  # an `os_event:` key (or any other) is not an escalation: write nothing
        return
    svc = ports.services()
    tenant, O, C = svc.settings.tenant_id, models.outbox, models.support_cases
    delivery = {"delivery": {"status": status, "reason": (reason or "")[:500] or None}}
    with svc.engine.begin() as conn:
        conn.execute(update(O).where(O.c.tenant_id == tenant, O.c.channel == _CHANNEL, O.c.template == "escalation",
                                     O.c.idempotency_key == key)
                     .values(status="sent" if status == "sent" else "skipped", sent_at=func.now(),
                             attempts=O.c.attempts + 1, payload=O.c.payload.op("||")(delivery)))
        if not key.startswith("escalation:intake:"):
            conn.execute(update(C).where(C.c.tenant_id == tenant, C.c.id == int(key.split(":")[1]))
                         .values(counsellor_status=status))
    if key.startswith("escalation:intake:"):
        IntakeStore(svc.engine, tenant).set_counsellor_status(key.removeprefix("escalation:intake:"), status)


def drop_counsellor_escalation(key: str, reason: str = "handoff_off") -> None:
    """The glue will not send this escalation (the host part that carries it is off): the outbox row is `skipped` with
    the reason, and the support case goes back to as it was before the row existed (`counsellor_status` and
    `counsellor_reason` NULL, only while still `pending`), in ONE transaction. The student never reads a refusal
    that nobody made."""
    if not key.startswith("escalation:") or key.startswith("escalation:intake:"):
        return
    svc = ports.services()
    tenant, O, C = svc.settings.tenant_id, models.outbox, models.support_cases
    delivery = {"delivery": {"status": "dropped", "reason": reason[:500]}}
    with svc.engine.begin() as conn:
        conn.execute(update(O).where(O.c.tenant_id == tenant, O.c.channel == _CHANNEL, O.c.template == "escalation",
                                     O.c.idempotency_key == key)
                     .values(status="skipped", sent_at=func.now(), attempts=O.c.attempts + 1,
                             payload=O.c.payload.op("||")(delivery)))
        conn.execute(update(C).where(C.c.tenant_id == tenant, C.c.id == int(key.split(":")[1]),
                                     C.c.counsellor_status == "pending")
                     .values(counsellor_status=None, counsellor_reason=None))
