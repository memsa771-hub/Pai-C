"""The EscalationSink port (Slice 8 spec §2.2, S8-D12; promised by Slice 7 S7-D10). Every support case is opened
through it: the standalone adapter always writes the case, and the Counsellor adapter (Task 7) may also tell the
Counsellor. The glue reads the Counsellor's pending escalations here and marks each one delivered."""

from typing import Literal, Protocol

from sqlalchemy import func, select, update

from app.os import models, ports
from app.os.contracts.escalation import EscalationV1

_CHANNEL = "counsellor"  # adapters.counsellor.escalation.CHANNEL (not imported: the replan code imports this port)


class EscalationSink(Protocol):
    def escalate(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        """Opens (or reuses) the support case for these events and returns its id."""
        ...


def pending_counsellor_escalations(limit: int = 100) -> list[EscalationV1]:
    """Escalations waiting for the glue to hand them to the Counsellor, oldest first."""
    svc = ports.services()
    O = models.outbox
    with svc.engine.connect() as conn:
        rows = conn.execute(select(O.c.payload).where(
            O.c.tenant_id == svc.settings.tenant_id, O.c.channel == _CHANNEL, O.c.status == "pending")
            .order_by(O.c.id).limit(limit)).scalars().all()
    return [EscalationV1.model_validate(p) for p in rows]


def mark_counsellor_delivery(key: str, status: Literal["sent", "refused"], reason: str | None = None) -> None:
    """Records the Counsellor's answer on the outbox row and on the support case (or the intake row). A refused
    escalation stays a support case, open, for a person in PAI OS (spec §2.5)."""
    from app.os.adapters.counsellor.store import IntakeStore

    svc = ports.services()
    tenant, O, C = svc.settings.tenant_id, models.outbox, models.support_cases
    delivery = {"delivery": {"status": status, "reason": (reason or "")[:500] or None}}
    with svc.engine.begin() as conn:
        conn.execute(update(O).where(O.c.tenant_id == tenant, O.c.channel == _CHANNEL, O.c.idempotency_key == key)
                     .values(status="sent" if status == "sent" else "skipped", sent_at=func.now(),
                             attempts=O.c.attempts + 1, payload=O.c.payload.op("||")(delivery)))
        if not key.startswith("escalation:intake:"):
            conn.execute(update(C).where(C.c.tenant_id == tenant, C.c.id == int(key.split(":")[1]))
                         .values(counsellor_status=status))
    if key.startswith("escalation:intake:"):
        IntakeStore(svc.engine, tenant).set_counsellor_status(key.removeprefix("escalation:intake:"), status)
