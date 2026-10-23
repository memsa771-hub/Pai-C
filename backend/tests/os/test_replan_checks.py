"""Slice 7 Task 3: the kernel's checks on replan operations (spec S7-D6), applying a replan, and the pause flag.
Fictional data."""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import select, update

from app.os import models
from app.os.compiler import compile_plan
from app.os.kernel import Kernel, StaleDraft
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.playbooks import load_playbook_dir
from app.os.replan.checks import check_operations, task_rows
from app.os.replan.ops import (
    AddTask, CancelProgramme, CancelTask, Escalate, Reprioritise, SkipTask, SwapProgramme, TaskRow, to_overrides,
)
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.test_golden import TEST_STUDENT

BOOK = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
TODAY = date(2027, 2, 1)
P1 = "tu-chemnitz-embedded-systems"
R = "fictional reason"


def compile_with(ops):
    return compile_plan(TEST_STUDENT, BOOK, {}, {}, TODAY, overrides=[o for op in ops for o in to_overrides(op)])


CURRENT = compile_with([])


def rows(**states) -> dict[str, TaskRow]:
    out = {}
    for t in CURRENT.tasks:
        state = states.get(t.instance_key.replace("@", "__").replace("-", "_"), "pending")
        out[t.instance_key] = TaskRow(t.instance_key, t.template_key, t.programme_ref, state, t.kind, t.critical,
                                      t.protected, t.latest_finish, t.slack_days, t.duration_days, t.depends_on)
    return out


def check(ops, tasks=None, confirmed=lambda ref: True, compile_fn=compile_with):
    return check_operations(ops, tasks or rows(), BOOK, compile_fn, CURRENT, confirmed)


def why(refused) -> list[str]:
    return [r["why"] for r in refused]


def test_unknown_template_refused():
    kept, refused = check([AddTask(template_key="no_such_step", reason=R)])
    assert kept == [] and "not a step" in why(refused)[0]


def test_missing_target_refused():
    assert "no step" in why(check([SkipTask(instance_key="nothing_here", reason=R)])[1])[0]


def test_started_target_refused():
    tasks = rows()
    tasks["travel_insurance"] = replace(tasks["travel_insurance"], state="running", kind="work")
    assert "started" in why(check([CancelTask(instance_key="travel_insurance", reason=R)], tasks)[1])[0]


def test_protected_target_refused():
    tasks = rows()
    tasks["blocked_account"] = replace(tasks["blocked_account"], protected=True)
    assert "protected" in why(check([SkipTask(instance_key="blocked_account", reason=R)], tasks)[1])[0]


def test_dependent_loses_input_refused():
    """review_visa_file needs travel_insurance (a hard edge): skipping it alone is refused..."""
    kept, refused = check([SkipTask(instance_key="travel_insurance", reason=R)])
    assert kept == [] and "needs it" in why(refused)[0]


def test_dependent_removed_too_is_fine():
    """...but cancelling a whole programme removes its dependents with it."""
    kept, refused = check([CancelProgramme(programme_ref=P1, reason=R)])
    assert refused == [] and len(kept) == 1


def test_critical_pushed_past_deadline_refused():
    at_risk = replace(CURRENT, tasks=tuple(replace(t, slack_days=-2) if t.instance_key == "visa_apply" else t
                                           for t in CURRENT.tasks), at_risk=True)
    fn = lambda ops: at_risk if ops else CURRENT  # noqa: E731  (any change makes visa_apply late)
    kept, refused = check([AddTask(template_key="review_visa_file", reason=R)], compile_fn=fn)
    assert kept == [] and "past its deadline" in why(refused)[0]


def test_unconfirmed_swap_refused():
    kept, refused = check([SwapProgramme(out_ref=P1, in_ref="uni-x", reason=R)], confirmed=lambda ref: False)
    assert kept == [] and "confirmed" in why(refused)[0]


def test_refused_op_dropped_rest_applied():
    """Review Focus #4: an unknown step and a started step are refused; the valid operations are kept."""
    tasks = rows()
    tasks["blocked_account"] = replace(tasks["blocked_account"], state="running", kind="work")
    ops = [AddTask(template_key="invented_step", reason=R), SkipTask(instance_key="blocked_account", reason=R),
           Reprioritise(instance_key="travel_insurance", before="review_visa_file", reason=R), Escalate(reason=R)]
    kept, refused = check(ops, tasks)
    assert [o.op for o in kept] == ["reprioritise", "escalate"] and len(refused) == 2


def test_task_rows_from_db(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb, load_playbook_dir(),
                      today=lambda: TODAY)
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    got = task_rows(engine, "pai", plan_id)
    assert "visa_apply" in got and ("review_visa_file", True) in got["visa_apply"].depends_on


@pytest.fixture
def svc(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    return PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb, load_playbook_dir(),
                       today=lambda: TODAY)


def test_apply_replan_numbered_revision_and_stale(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    contract, sha = svc._contract(plan_id)
    draft = compile_plan(contract, svc._pinned(plan_id), {}, {}, TODAY,
                         overrides=to_overrides(CancelProgramme(programme_ref=P1, reason=R)))
    with pytest.raises(StaleDraft):
        svc.kernel.apply_replan(plan_id, 7, draft, based_on="f" * 64)
    number = svc.kernel.apply_replan(plan_id, 7, draft, based_on=sha)
    with engine.connect() as conn:
        cause = conn.execute(select(models.plan_revisions.c.cause).where(
            models.plan_revisions.c.plan_id == plan_id, models.plan_revisions.c.number == number)).scalar_one()
    assert cause == "replan:7"


def test_pause_flag(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    assert svc.kernel.changes_paused(plan_id) is False
    svc.kernel.set_changes_paused(plan_id, True)
    assert svc.kernel.changes_paused(plan_id) is True
    svc.kernel.set_changes_paused(plan_id, False)
    assert svc.kernel.changes_paused(plan_id) is False


def test_replan_revisions_today_counts_cause(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    R_ = models.plan_revisions
    with engine.begin() as conn:  # revisions as the kernel wrote them (simulated): two replans and a swap today
        for n, cause in enumerate(["replan:1", "programme_swap", "replan:2"], start=2):
            conn.execute(R_.insert().values(tenant_id="pai", plan_id=plan_id, number=n, cause=cause, diff={}))
        conn.execute(update(R_).where(R_.c.plan_id == plan_id, R_.c.number == 1).values(
            cause="replan:0", created_at=R_.c.created_at - timedelta(days=2)))  # an older replan does not count
    assert svc.kernel.replan_revisions_today(plan_id) == 2


def test_op_that_breaks_the_plan_refused():
    """Final review C1: an operation that makes the plan uncompilable is refused, never an exception."""
    from app.os.compiler import CompileError

    def broken(ops):
        if ops:
            raise CompileError("cycle: a -> b -> a")
        return CURRENT

    kept, refused = check([Reprioritise(instance_key="travel_insurance", before="review_visa_file", reason=R),
                           Escalate(reason=R)], compile_fn=broken)
    assert [o.op for o in kept] == ["escalate"] and "invalid" in why(refused)[0]


def test_add_task_needs_its_step_in_the_plan():
    """Final review I7: re-adding a step the plan does not have would silently change nothing: refused."""
    kept, refused = check([AddTask(template_key="admission_result", reason=R)])  # per programme, no programme given
    assert kept == [] and "not in the plan" in why(refused)[0]
    kept, refused = check([AddTask(template_key="admission_result", programme_ref="not-in-plan", reason=R)])
    assert kept == [] and refused
    kept, _ = check([AddTask(template_key="admission_result", programme_ref=P1, reason=R)])
    assert len(kept) == 1


def test_replan_count_restarts_after_resume(svc, engine):
    """Final review I10: an admin who resumes the plan gives it a fresh daily allowance."""
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    R_ = models.plan_revisions
    with engine.begin() as conn:
        for n, cause in enumerate(["replan:1", "replan:2", "replan:3"], start=2):
            conn.execute(R_.insert().values(tenant_id="pai", plan_id=plan_id, number=n, cause=cause, diff={}))
    assert svc.kernel.replan_revisions_today(plan_id) == 3
    svc.kernel.set_changes_paused(plan_id, True)
    svc.kernel.set_changes_paused(plan_id, False)
    assert svc.kernel.replan_revisions_today(plan_id) == 0
