import threading

import pytest
from sqlalchemy import func, select

from app.os import models
from app.os.kernel import Kernel, Outcome
from tests.os.kernel_helpers import contract, draft, kernel, playbook


def _count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).one()


def test_create_plan_writes_tasks_events_and_requests(engine, clean):
    k = kernel(engine)
    d = draft()
    ref = k.create_plan(contract(), d)
    assert ref.created and ref.revision == 1
    assert _count(engine, models.tasks) == len(d.tasks)
    assert _count(engine, models.task_edges) == 2  # a -> apply@p1 -> visa
    a = _task(engine, ref.plan_id, "a")
    assert (a.state, a.attempt) == ("ready", 1)
    with engine.connect() as conn:
        req = conn.execute(select(models.enqueue_requests)).one()
        types = set(conn.execute(select(models.events.c.type)).scalars())
    assert (req.task_id, req.attempt, req.sent) == (a.id, 1, False)
    assert {"plan_created", "task_state"} <= types
    assert _task(engine, ref.plan_id, "apply@p1").state == "pending"
    assert _task(engine, ref.plan_id, "apply@p1").due_at == d.tasks[1].latest_finish


def test_create_twice_same_content_is_noop(engine, clean):
    k = kernel(engine)
    first = k.create_plan(contract(), draft())
    second = k.create_plan(contract(), draft())
    assert (second.plan_id, second.created) == (first.plan_id, False)
    assert _count(engine, models.plan_revisions) == 1


def test_changed_contract_creates_revision(engine, clean):
    k = kernel(engine)
    first = k.create_plan(contract(["p1"]), draft(refs=("p1",)))
    second = k.create_plan(contract(["p1", "p2"]), draft(refs=("p1", "p2")))
    assert second.plan_id == first.plan_id and second.revision == 2
    assert _count(engine, models.plans) == 1
    assert _task(engine, first.plan_id, "apply@p2").state == "pending"


def test_concurrent_create_one_plan(engine, clean):
    k = kernel(engine)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def run():
        try:
            barrier.wait()
            results.append(k.create_plan(contract(), draft()))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert _count(engine, models.plans) == 1
    assert len({r.plan_id for r in results}) == 1 and sorted(r.created for r in results) == [False, True]


def test_work_result_promotes_student_task(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    assert k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    assert _task(engine, ref.plan_id, "a").state == "done"
    assert _task(engine, ref.plan_id, "apply@p1").state == "waiting_student"


def test_stale_attempt_ignored(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.apply_result(a.id, 7, Outcome("done"))
    assert _task(engine, ref.plan_id, "a").state == "ready"


def test_dependency_done_promotes_successor(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    apply = _task(engine, ref.plan_id, "apply@p1")
    assert k.complete_student_task(apply.id, "stu-1", {})
    assert _task(engine, ref.plan_id, "visa").state == "waiting_student"


def test_complete_twice_is_noop(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    apply = _task(engine, ref.plan_id, "apply@p1")
    with engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(models.events)).scalar_one()
    assert k.complete_student_task(apply.id, "stu-1", {"note": "sent"}) is True
    mid = _count(engine, models.events)
    assert k.complete_student_task(apply.id, "stu-1", {"note": "sent"}) is False
    assert _count(engine, models.events) == mid > before


def test_wrong_student_cannot_complete(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    apply = _task(engine, ref.plan_id, "apply@p1")
    with pytest.raises(PermissionError):
        k.complete_student_task(apply.id, "someone-else", {})


def test_failed_then_retry(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("failed", reason="workflow_error"))
    assert _task(engine, ref.plan_id, "a").state == "failed"
    assert k.retry(a.id) == 2
    assert (_task(engine, ref.plan_id, "a").state, _count(engine, models.enqueue_requests)) == ("ready", 2)


def test_needs_review_then_complete_review(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("needs_review"))
    assert _task(engine, ref.plan_id, "a").state == "waiting_review"
    k.complete_review(a.id, {"ok": True})
    assert _task(engine, ref.plan_id, "a").state == "done"


def test_rollback_leaves_nothing(engine, clean, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(Kernel, "_event", boom)
    with pytest.raises(RuntimeError):
        kernel(engine).create_plan(contract(), draft())
    for table in (models.plans, models.tasks, models.enqueue_requests, models.plan_revisions):
        assert _count(engine, table) == 0


def test_upgrade_keeps_started_tasks(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    v2 = playbook(version=2, title_a="Milestone A (v2)", extra_tasks=[
        {"template_key": "b", "task_type": "student.act", "title": "New step", "kind": "student", "inbox_kind": "act"}])
    rev = k.upgrade_playbook(ref.plan_id, draft(v2))
    assert rev == 2
    assert _task(engine, ref.plan_id, "a").title == "Milestone A"
    assert _task(engine, ref.plan_id, "b").state == "waiting_student"
    with engine.connect() as conn:
        diff = conn.execute(select(models.plan_revisions.c.diff).where(models.plan_revisions.c.number == 2)).scalar_one()
        pin = conn.execute(select(models.playbook_pins.c.version)).scalar_one()
    assert diff["skipped_started"] == ["a"] and diff["added"] == ["b"] and pin == 2
    assert _task(engine, ref.plan_id, "plan_updated@r2").state == "waiting_student"


def test_revise_unchanged_returns_none(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())
    assert k.revise(ref.plan_id, "deadline_recompute", draft()) is None
    assert _count(engine, models.plan_revisions) == 1


def test_revise_cancels_removed_unstarted(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(["p1", "p2"]), draft(refs=("p1", "p2")))
    rev = k.revise(ref.plan_id, "programme_dropped", draft(refs=("p1",)))
    assert rev == 2
    assert _task(engine, ref.plan_id, "apply@p2").state == "cancelled"


def test_at_risk_plan_emits_slack_low(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft(day="2027-02-01"))
    with engine.connect() as conn:
        status = conn.execute(select(models.plans.c.status)).scalar_one()
        types = set(conn.execute(select(models.events.c.type)).scalars())
    assert status == "at_risk" and "slack_low" in types
    assert ref.created
