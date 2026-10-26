"""The standalone escalation adapter (Slice 8 spec §2.5): the support case, exactly as Slice 7's `Replanner.support`
opened it, plus the composite sink that runs every adapter in order."""

from collections.abc import Callable, Sequence

from sqlalchemy import Engine, select

from app.os import models
from app.os.ports.escalation import EscalationSink
from app.os.replan.store import SupportStore


class StandaloneSink:
    def __init__(self, engine: Engine, tenant_id: str, student_of: Callable[[int], str] | None = None) -> None:
        self.engine, self.tenant_id = engine, tenant_id
        self.student_of = student_of or self._student_of
        self.cases = SupportStore(engine, tenant_id)

    def _student_of(self, plan_id: int) -> str:
        P = models.plans
        with self.engine.connect() as conn:
            return conn.execute(select(P.c.student_ref).where(P.c.tenant_id == self.tenant_id, P.c.id == plan_id)
                                ).scalar_one()

    def escalate(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        found = self.cases.for_event(event_ids[0]) if event_ids else None  # one case per triggering event
        if found is not None:
            return found.id
        return self.cases.open(plan_id, self.student_of(plan_id), reason, event_ids, proposal_id)


class CompositeSink:
    """Runs each sink in order; the first (the standalone one) owns the case id."""

    def __init__(self, sinks: Sequence[EscalationSink]) -> None:
        self.sinks = list(sinks)

    def escalate(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        ids = [s.escalate(plan_id, event_ids, reason, proposal_id) for s in self.sinks]
        return ids[0]
