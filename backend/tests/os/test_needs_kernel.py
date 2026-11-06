"""P1-T8 Task 2: the kernel closes an answered request step as done, and blocks a waiting step that loses its data.
Real kernel, Postgres. Fictional route and student."""

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import select

from app.os import models
from app.os.compiler import compile_plan
from app.os.requests.state import QuestionRef, StudentState
from tests.os.kernel_helpers import kernel
from tests.os.test_compile_needs import INTER2, OBTAINED, TOTAL, contract, merit

TODAY = date(2027, 3, 1)
NOTHING = StudentState()
TYPED = StudentState(facts={OBTAINED: "stated", TOTAL: "stated"})
KEY = f"provide@fact:{OBTAINED}:stated"

pytestmark = pytest.mark.req("R-17")


def compiled(state, book=INTER2):
    return compile_plan(contract(), book, {}, merit(), TODAY, student=state)


def row(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).one()


def causes(engine, task_id) -> list[str]:
    with engine.connect() as conn:
        return [e.payload["cause"] for e in conn.execute(select(models.events).where(
            models.events.c.task_id == task_id, models.events.c.type == "task_state").order_by(models.events.c.id))]


def test_the_missing_data_is_asked_and_the_steps_that_need_it_wait(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    assert row(engine, ref.plan_id, KEY).state == "waiting_student"
    assert row(engine, ref.plan_id, "admission_form").state == "blocked"
    assert row(engine, ref.plan_id, "admission_form").blocked_reason == f"awaiting_fact:{OBTAINED}"
    assert row(engine, ref.plan_id, "merit_list@p1").state == "blocked"


def test_answered_waiting_step_closes_as_done(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    asked = row(engine, ref.plan_id, KEY)
    assert k.revise(ref.plan_id, "student_fact_changed", compiled(TYPED)) is not None
    closed = row(engine, ref.plan_id, f"{KEY}#d2")  # renamed, so the same request can come back
    assert (closed.id, closed.state) == (asked.id, "done")
    assert causes(engine, asked.id)[-1] == "request_answered"
    form = row(engine, ref.plan_id, "admission_form")
    assert (form.state, form.blocked_reason) == ("waiting_student", None)  # unblocked, now the student's step
    assert row(engine, ref.plan_id, "merit_list@p1").state == "blocked"  # still waits for the mark sheet
    assert row(engine, ref.plan_id, f"provide@fact:{OBTAINED}:shown").state == "waiting_student"


def test_a_request_removed_for_another_reason_is_cancelled(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    asked = row(engine, ref.plan_id, KEY)
    assert k.revise(ref.plan_id, "gate_off", compiled(None)) is not None  # needs ignored: the requests go
    gone = row(engine, ref.plan_id, f"{KEY}#c2")
    assert (gone.id, gone.state) == (asked.id, "cancelled")
    assert causes(engine, asked.id)[-1] == "gate_off"


def test_a_request_asked_again_is_a_fresh_step(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    k.revise(ref.plan_id, "student_fact_changed", compiled(TYPED))
    k.revise(ref.plan_id, "student_fact_changed", compiled(NOTHING))  # the student took the marks back
    again = row(engine, ref.plan_id, KEY)
    assert again.state == "waiting_student" and again.id != row(engine, ref.plan_id, f"{KEY}#d2").id


def test_waiting_step_gaining_a_t8_block_is_blocked(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(TYPED))
    assert row(engine, ref.plan_id, "admission_form").state == "waiting_student"
    doubt = StudentState(facts=TYPED.facts, questions={f"fact:{OBTAINED}": QuestionRef("vault", "profile_issue:1")})
    assert k.revise(ref.plan_id, "student_fact_changed", compiled(doubt)) is not None
    form = row(engine, ref.plan_id, "admission_form")
    assert (form.state, form.blocked_reason) == ("blocked", f"which_is_right:{OBTAINED}")
    assert row(engine, ref.plan_id, f"which_is_right@fact:{OBTAINED}:shown").state == "waiting_student"
    # the answer: the question goes, the request is done, the step is the student's again
    assert k.revise(ref.plan_id, "student_fact_changed", compiled(TYPED)) is not None
    assert row(engine, ref.plan_id, f"which_is_right@fact:{OBTAINED}:shown#d3").state == "done"
    assert row(engine, ref.plan_id, "admission_form").state == "waiting_student"


def test_other_block_codes_keep_todays_rule(engine, clean):
    """A waiting student step that gains any other blocked reason stays as it is (today's rule: only a ready step is
    blocked), so a plan without needs is revised as it always was."""
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(TYPED))
    d = compiled(TYPED)
    odd = tuple(replace(t, blocked_reason="fact_missing:x") if t.instance_key == "admission_form" else t
                for t in d.tasks)
    assert k.revise(ref.plan_id, "fact_changed", replace(d, tasks=odd)) is not None
    form = row(engine, ref.plan_id, "admission_form")
    assert (form.state, form.blocked_reason) == ("waiting_student", "fact_missing:x")


def test_same_state_same_draft_makes_no_revision(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    assert k.revise(ref.plan_id, "deadline_recompute", compiled(NOTHING)) is None
    k.revise(ref.plan_id, "student_fact_changed", compiled(TYPED))
    assert k.revise(ref.plan_id, "deadline_recompute", compiled(TYPED)) is None
