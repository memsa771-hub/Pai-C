"""Test helper: an intake made `current` the way only the gate may (a locked row and the private store method). Tests that
need a current intake without building a whole green registry use this; the real path is `coverage.gate.pass_gate`."""

from datetime import datetime

from app.os.intakes import IntakeStore


def make_current(engine, intake_id: int, at: datetime, tenant: str = "pai"):
    store = IntakeStore(engine, tenant)
    with engine.begin() as conn:
        store._gate_lock(conn, intake_id)
        return store._gate_set_current(conn, intake_id, at)
