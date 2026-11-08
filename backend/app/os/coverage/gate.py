"""The intake `current` gate (P2 spec §4.9; master R-66). An intake becomes `current` only when its own coverage gate
(R-35 a to d) is green. The gate pass is recorded on the intake row; this is the only caller that records one."""

from datetime import datetime

from sqlalchemy import Engine

from app.os.coverage import report
from app.os.intakes.store import Intake, IntakeError, IntakeStore


class GateRed(IntakeError):
    def __init__(self, failing: list[dict]) -> None:
        super().__init__(f"the coverage gate is red: {len(failing)} failing item(s)")
        self.failing = failing


def pass_gate(engine: Engine, tenant_id: str, intake_id: int, now: datetime) -> Intake:
    """Moves an open intake to `current` when its gate is green; raises `GateRed` with the failing items otherwise.
    The report is read again here, never taken from the caller."""
    rep = report.build(engine, tenant_id, intake_id, now)
    if not rep.green:
        raise GateRed(rep.failing())
    return IntakeStore(engine, tenant_id).set_state(intake_id, "current", gate_passed_at=now)
