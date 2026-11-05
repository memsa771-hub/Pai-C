"""P1-T5 Task 2: the PlanActions port completes a student step through the one shared inbox function (R-04).
Fictional data; plan and task rows are the tests' own writes."""

import pytest
from sqlalchemy import select

from app.os import models, ports
from app.os.inbox_actions import StepActionError
from app.os.ports import plan_actions
from test_counsellor_intake_v2 import svc  # noqa: F401
from test_plan_summary import STUDENT, plan, task

pytestmark = pytest.mark.req("R-04")


@pytest.fixture
def os_on(svc):  # noqa: F811
    ports.configure(svc)
    try:
        yield svc
    finally:
        ports.configure(None)


def task_id(engine, plan_id, key) -> int:
    with engine.connect() as conn:
        return conn.execute(select(models.tasks.c.id).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).scalar_one()


def state(engine, tid) -> str:
    with engine.connect() as conn:
        return conn.execute(select(models.tasks.c.state).where(models.tasks.c.id == tid)).scalar_one()


def test_complete_waiting_step_then_repeat(os_on, engine):
    p = plan(engine)
    task(engine, p, "apply@p1", "waiting_student", kind="student")
    tid = task_id(engine, p, "apply@p1")
    assert plan_actions.complete_step(STUDENT, tid) == "done"
    assert state(engine, tid) == "done"
    assert plan_actions.complete_step(STUDENT, tid) == "already_done"


def test_review_step_is_refused(os_on, engine):
    p = plan(engine)
    task(engine, p, "review_pack@p1", "waiting_student", kind="student")
    tid = task_id(engine, p, "review_pack@p1")
    with pytest.raises(StepActionError) as e:
        plan_actions.complete_step(STUDENT, tid)
    assert e.value.code == "review_required"
    assert state(engine, tid) == "waiting_student"


def test_another_students_step_is_not_yours(os_on, engine):
    p = plan(engine)
    task(engine, p, "apply@p1", "waiting_student", kind="student")
    tid = task_id(engine, p, "apply@p1")
    with pytest.raises(StepActionError) as e:
        plan_actions.complete_step("someone-else", tid)
    assert e.value.code == "not_yours"
    assert state(engine, tid) == "waiting_student"


def test_work_step_is_not_yours(os_on, engine):
    p = plan(engine)
    task(engine, p, "fetch", "waiting_student", kind="work")
    with pytest.raises(StepActionError) as e:
        plan_actions.complete_step(STUDENT, task_id(engine, p, "fetch"))
    assert e.value.code == "not_yours"


def test_unknown_step_is_not_found(os_on):
    with pytest.raises(StepActionError) as e:
        plan_actions.complete_step(STUDENT, 987654)
    assert e.value.code == "not_found"


def test_step_not_waiting_is_refused(os_on, engine):
    p = plan(engine)
    task(engine, p, "apply@p1", "pending", kind="student")
    with pytest.raises(StepActionError) as e:
        plan_actions.complete_step(STUDENT, task_id(engine, p, "apply@p1"))
    assert e.value.code == "not_waiting"
    assert "not waiting for the student" in e.value.message
