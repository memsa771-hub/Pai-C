"""The end-of-test check (P1-T10 A3, R-04, R-05): `assert_consistent` is the last line of a scripted flow. It runs one
sweep and the OS intake (so a change has had its one sweep), then the replan rules for its events, then the consistency rules 1-8 in `settled` mode, which
tolerates nothing pending, and asserts every count is zero. It writes nothing (`open_cases=False`). On failure it
names the rule and the codes, never a value or a student reference."""

from collections.abc import Callable
from contextlib import contextmanager
from unittest.mock import patch

from app import pai_os_bridge as bridge
from app.config import config
from app.os import ports
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore


def run_intake() -> list[tuple[str, str | None]]:
    """What the OS worker does for each pending Counsellor intake row, called directly."""
    svc = ports.services()
    store = IntakeStore(svc.engine, svc.settings.tenant_id)
    done = []
    for intake in store.pending():
        result = process(svc, intake)
        store.finish(intake.id, result.status, result.reason, result.plan_id)
        done.append((result.status, result.reason))
    return done


def run_replans() -> int:
    """What the OS replan sweep and its workflow do for each pending event, called directly: the rules, then the
    decision (a handover becomes a support case). Returns how many events were handled."""
    from app.os.api.replan import replanner_for
    from app.os.replan import events
    from app.os.replan.rules import Handover, Retry, rules_for

    svc = ports.services()
    replanner = replanner_for(svc)
    done = 0
    for e in events.pending(svc.engine, svc.settings.tenant_id):
        got = rules_for(e, replanner.state(e.plan_id, with_below=e.type == "student_fact_changed"),
                        replanner.config(e.plan_id))
        if isinstance(got, Handover):
            replanner.support(e.plan_id, [e.id], got.reason)
        elif not isinstance(got, Retry):
            replanner.decide(e.plan_id, [e.id], "rules", got)
        done += 1
    return done


@contextmanager
def _session(db_or_factory):
    if callable(db_or_factory) and not hasattr(db_or_factory, "execute"):
        with db_or_factory() as db:
            yield db
    else:
        yield db_or_factory


@contextmanager
def _nothing():
    yield


def findings(db_or_factory: Callable | object, *, sweep: bool = True) -> dict:
    """The result of the settled check (`{"students", "findings": {rule: n}, ...}`), after one sweep when asked."""
    with _session(db_or_factory) as db:
        if sweep:
            bridge.sweep_once(db)
            run_intake()
            run_replans()
            bridge.sweep_once(db)  # whatever the intake raised for the Counsellor (events, escalations) goes out too
        return bridge.consistency_run(db, mode="settled", open_cases=False)


def assert_consistent(db_or_factory: Callable | object, *, sweep: bool = True, handoff: bool = False) -> dict:
    """`handoff=True` switches CONNECT_HANDOFF on for the check, for a flow whose own world has only another part on
    (the job needs the hand-off part; the Vault-only worlds of T4 and T8 do not set it)."""
    with patch.object(config, "CONNECT_HANDOFF", True, create=True) if handoff else _nothing():
        got = findings(db_or_factory, sweep=sweep)
    assert "mounted" not in got and "skipped" not in got, f"the consistency check did not run: {got}"
    detail = dict(sorted(got["findings"].items()))
    assert not got["findings"] and not got["errors"], f"consistency findings per rule {detail}, errors {got['errors']}"
    return got
