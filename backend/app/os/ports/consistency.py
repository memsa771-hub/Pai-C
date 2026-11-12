"""The consistency port (P1-T10 A1, R-05): what the host's consistency job reads and writes in PAI OS. It reads the
read-only per-student view and writes only the consistency cases and run rows. A case is for a person; it is never a
support case of the plan, never a message and never reaches the escalation channel (R-45). Each call raises
`ports.OsUnavailable` when PAI OS is not mounted."""

from datetime import date

from app.os import ports
from app.os.consistency import store as case_store
from app.os.consistency import view
from app.os.consistency.view import OsSide


def _store() -> case_store.ConsistencyStore:
    svc = ports.services()
    return case_store.ConsistencyStore(svc.engine, svc.settings.tenant_id)


def side(student_ref: str, export: dict | None) -> OsSide:
    svc = ports.services()
    return view.os_side(svc.engine, svc.settings.tenant_id, student_ref, export)


def students() -> list[str]:
    svc = ports.services()
    return view.counsellor_students(svc.engine, svc.settings.tenant_id)


def open_case(student_ref: str, rule: int, plan_id: int | None, codes: list[str]) -> tuple[int, bool]:
    """Opens the student's case for the rule, or only touches the open one. `(case id, created)`."""
    return _store().open_or_touch(student_ref, rule, plan_id, codes)


def cases(status: str | None = None) -> list[case_store.Case]:
    return _store().list(status)


def resolve(case_id: int, note: str) -> bool:
    return _store().resolve(case_id, note)


def claim_run(run_date: date, mode: str) -> int | None:
    """The run id, or None when this date already has a run (another replica won)."""
    return _store().claim_run(run_date, mode)


def finish_run(run_id: int, counts: dict) -> None:
    _store().finish_run(run_id, counts)
