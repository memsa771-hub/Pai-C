"""The intake `current` gate (P2 spec §4.9; master R-66). An intake becomes `current` only when its own coverage gate
(R-35 a to d) is green. The gate pass is recorded on the intake row; this is the only caller that records one. An intake that
is already current but whose gate has turned red is flagged by reading (e) of the report; it is never reverted by itself."""

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
    The intake row is locked first and the report is read after the lock, in the same transaction as the write, so two
    callers cannot both pass and nothing is taken from the caller."""
    store = IntakeStore(engine, tenant_id)
    with engine.begin() as conn:
        found = store._gate_lock(conn, intake_id)
        if found is None:
            raise IntakeError(f"no intake {intake_id}")
        if found.state != "open":
            raise IntakeError(f"the intake is {found.state}, not open")
        rep = report.build(engine, tenant_id, intake_id, now)
        if not rep.green:
            raise GateRed(rep.failing())
        return store._gate_set_current(conn, intake_id, now)
