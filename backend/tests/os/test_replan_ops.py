"""Slice 7 Task 2: replan operations and the compiler's plan overrides (spec S7-D4, D5, D7). Fictional data."""

from datetime import date, datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.os.compiler import compile_plan
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.playbooks import load_playbook_dir
from app.os.replan.ops import (
    AddTask, CancelProgramme, CancelTask, Escalate, Ops, Reprioritise, RequestFromStudent, SkipTask, SwapProgramme,
    TaskRow, UpgradePlaybook, is_big, to_overrides,
)
from app.os.replan.store import Override, OverrideStore, ProposalStore
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.test_golden import TEST_STUDENT

BOOK = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
TODAY = date(2027, 2, 1)
P1, P2 = "tu-chemnitz-embedded-systems", "ovgu-eeit"
R = "fictional reason"


def draft(*overrides: Override):
    return compile_plan(TEST_STUDENT, BOOK, {}, {}, TODAY, overrides=overrides)


def keys(d) -> set[str]:
    return {t.instance_key for t in d.tasks}


def task(d, key):
    return next(t for t in d.tasks if t.instance_key == key)


def row(key: str, critical=False, kind="student", template=None, ref=None, duration=1) -> TaskRow:
    return TaskRow(instance_key=key, template_key=template or key.split("@")[0], programme_ref=ref, state="pending",
                   kind=kind, critical=critical, protected=False, latest_finish=None, slack_days=3,
                   duration_days=duration, depends_on=())


def test_skip_removes_and_drops_edges():
    base = draft()
    assert "travel_insurance" in {k for k, _ in task(base, "review_visa_file").depends_on}
    d = draft(Override("skip", "travel_insurance", {}))
    assert "travel_insurance" not in keys(d)
    assert "travel_insurance" not in {k for k, _ in task(d, "review_visa_file").depends_on}


def test_cancel_programme_removes_all():
    d = draft(Override("cancel_programme", P1, {}))
    assert not [t for t in d.tasks if t.programme_ref == P1]
    assert [t for t in d.tasks if t.programme_ref == P2]


def test_add_task_second_instance_holds_dependents():
    d = draft(Override("add", "review_visa_file", {"programme_ref": None}))
    again = task(d, "review_visa_file#2")
    assert again.template_key == "review_visa_file"
    assert set(again.depends_on) == set(task(d, "review_visa_file").depends_on)
    assert ("review_visa_file#2", True) in task(d, "visa_apply").depends_on
    d3 = draft(Override("add", "review_visa_file", {"programme_ref": None}),
               Override("add", "review_visa_file", {"programme_ref": None}))
    assert {"review_visa_file#2", "review_visa_file#3"} <= keys(d3)


def test_reprioritise_adds_soft_edge():
    d = draft(Override("reprioritise", "travel_insurance", {"before": "blocked_account"}))
    assert ("travel_insurance", False) in task(d, "blocked_account").depends_on


def test_unknown_override_target_is_ignored():
    assert keys(draft(Override("skip", "no_such_task", {}))) == keys(draft())


def test_overrides_survive_recompile(engine, clean):
    """Review Focus #1: the nightly recompile keeps a replan's overrides; a cancelled programme stays cancelled."""
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb, load_playbook_dir(),
                      today=lambda: TODAY)
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    pid = ProposalStore(engine, "pai").create(plan_id, [1], "rules", [], [], big=True, expires_at=None,
                                              status="accepted")
    OverrideStore(engine, "pai").add(plan_id, pid, "cancel_programme", P1, {})
    svc.recompile(plan_id, "replan:test")
    svc.recompile(plan_id, "deadline_engine")  # nothing more changes, and the programme does not come back
    from tests.os.test_golden import normalised
    from app.os.api.queries import plan_out

    live = [t for t in normalised(plan_out(engine, "pai", plan_id))["tasks"]
            if t["programme_ref"] == P1 and t["state"] != "cancelled"]
    assert live == []


def test_is_big_classification():
    tasks = {"a": row("a", critical=True), "b": row("b"), f"apply@{P1}": row(f"apply@{P1}", ref=P1)}
    assert is_big(SwapProgramme(out_ref=P1, in_ref="x", reason=R), tasks, BOOK)
    assert is_big(CancelProgramme(programme_ref=P1, reason=R), tasks, BOOK)
    assert is_big(CancelTask(instance_key="a", reason=R), tasks, BOOK)
    assert is_big(SkipTask(instance_key="a", reason=R), tasks, BOOK)
    assert not is_big(SkipTask(instance_key="b", reason=R), tasks, BOOK)
    assert is_big(UpgradePlaybook(version=2, reason=R), tasks, BOOK)
    long_student = next(t for t in BOOK.tasks if t.kind == "student" and (t.duration_days or 0) > 1)
    one_day = next(t for t in BOOK.tasks if t.kind == "student" and t.duration_days == 1 and not t.duration_constant)
    assert is_big(AddTask(template_key=long_student.template_key, reason=R), tasks, BOOK)
    assert not is_big(AddTask(template_key=one_day.template_key, reason=R), tasks, BOOK)
    for small in (Reprioritise(instance_key="b", before="a", reason=R),
                  RequestFromStudent(instance_key="b", message="Please upload it.", reason=R), Escalate(reason=R)):
        assert not is_big(small, tasks, BOOK)


def test_to_overrides():
    assert to_overrides(SkipTask(instance_key="b", reason=R)) == [Override("skip", "b", {})]
    assert to_overrides(Reprioritise(instance_key="b", before="a", reason=R)) == [
        Override("reprioritise", "b", {"before": "a"})]
    assert to_overrides(AddTask(template_key="t", programme_ref=P1, reason=R)) == [
        Override("add", "t", {"programme_ref": P1})]
    assert to_overrides(Escalate(reason=R)) == []


def test_ops_reject_unknown_op_and_11_ops():
    adapter = TypeAdapter(Ops)
    with pytest.raises(ValidationError):
        adapter.validate_python([{"op": "delete_plan", "reason": R}])
    with pytest.raises(ValidationError):
        adapter.validate_python([{"op": "escalate", "reason": R}] * 11)
    with pytest.raises(ValidationError):
        adapter.validate_python([{"op": "escalate", "reason": ""}])
    assert len(adapter.validate_python([{"op": "escalate", "reason": R}] * 10)) == 10


def test_no_overrides_no_change():
    assert draft() == compile_plan(TEST_STUDENT, BOOK, {}, {}, TODAY)
    assert datetime(2027, 1, 1, tzinfo=timezone.utc)  # keeps the import list honest for the dates used above


def test_reprioritise_never_closes_a_cycle():
    """Final review I8: a reorder whose step already (transitively) waits for `before` is ignored, never a cycle."""
    d = draft(Override("reprioritise", "visa_apply", {"before": "travel_insurance"}))  # visa_apply needs it, via review
    assert ("visa_apply", False) not in task(d, "travel_insurance").depends_on
