"""P1-T3 Task 1: a missing consent pauses an existing plan, or holds a decision that has no plan yet (R-10, P1-D11).
Nothing is escalated for a missing consent. A later version with consent resumes the plan or plans the held decision.
Fictional exports from app/os/contracts/samples/v2; reuses the helpers of the v2 intake tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.os import models
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.outbox import Outbox
from app.os.workers.reminders import run_reminders
from test_counsellor_intake_v2 import (NEW_PLACES, P, T, chosen, plan_row, run, svc,  # noqa: F401
                                                v1)

pytestmark = pytest.mark.req("R-10")

DUE = datetime(2027, 5, 18, 12, tzinfo=timezone.utc)  # inside the slack-gone window of the sample plan's tasks
NO_STUDENT = {"authorized_at": None}
NO_GUARDIAN = {"guardian_required": True, "guardian_authorized_at": None}


def events_of(svc, plan_id: int, type_: str) -> list:
    E = models.events
    with svc.engine.connect() as conn:
        return list(conn.execute(select(E).where(E.c.plan_id == plan_id, E.c.type == type_).order_by(E.c.id)).all())


def task_states(svc, plan_id: int) -> dict[str, str]:
    with svc.engine.connect() as conn:
        return {r.instance_key: r.state for r in conn.execute(select(T).where(T.c.plan_id == plan_id))}


def case_count(svc) -> int:
    with svc.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.support_cases)).scalar()


def intake_rows(svc) -> int:
    with svc.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.counsellor_intake)).scalar()


def test_missing_student_consent_holds_without_escalation(svc):
    r = run(svc, chosen(1, **NO_STUDENT))
    assert (r.status, r.reason, r.plan_id) == ("held", "consent_missing", None)
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(P)).scalar() == 0
    assert case_count(svc) == 0
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get("d-v1").id, r.status, r.reason, r.plan_id)  # the intake status accepts `held`
    got = store.get("d-v1")
    assert (got.status, got.reason, got.counsellor_status) == ("held", "consent_missing", None)


def test_guardian_missing_holds(svc):
    r = run(svc, chosen(1, **NO_GUARDIAN))
    assert (r.status, r.reason, r.plan_id) == ("held", "consent_missing", None)
    assert case_count(svc) == 0


def test_guardian_given_plans(svc):
    r = run(svc, chosen(1, guardian_required=True, guardian_authorized_at="2027-01-10T10:00:00+05:00"))
    assert r.status == "planned"


def test_consent_withdrawn_pauses_plan(svc):
    first = run(svc, chosen(1))
    assert first.status == "planned"
    r = run(svc, chosen(2, **NO_STUDENT))
    assert (r.status, r.reason, r.plan_id) == ("paused", "consent_missing", first.plan_id)
    assert plan_row(svc, first.plan_id).status == "paused"
    (event,) = events_of(svc, first.plan_id, "plan_paused")
    assert event.payload == {"reason": "consent_missing"}
    assert case_count(svc) == 0
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get("d-v2").id, r.status, r.reason, r.plan_id)  # the intake status accepts `paused`
    # a paused plan sends no reminders, even after its task dates have passed
    box = Outbox(svc.engine, "pai")
    assert run_reminders(svc.engine, box, DUE, "pai") == 0
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.outbox)).scalar() == 0
    # and promotes no task when one finishes: `application_documents` waits on `choose_programmes`
    docs = "application_documents@ovgu-eeit"
    assert task_states(svc, first.plan_id)[docs] == "pending"
    with svc.engine.connect() as conn:
        choose = conn.execute(select(T.c.id).where(T.c.plan_id == first.plan_id,
                                                   T.c.instance_key == "choose_programmes")).scalar_one()
    assert svc.kernel.complete_student_task(choose, "ws-sample-1", {})
    after = task_states(svc, first.plan_id)
    assert (after["choose_programmes"], after[docs]) == ("done", "pending")
    assert plan_row(svc, first.plan_id).status == "paused"
    # resuming promotes what became ready meanwhile
    assert svc.kernel.resume_plan(first.plan_id)
    assert task_states(svc, first.plan_id)[docs] == "waiting_student"


def test_active_plan_sends_reminders(svc):
    """The control of the pause test: the same plan, not paused, does send reminders on that date."""
    run(svc, chosen(1))
    assert run_reminders(svc.engine, Outbox(svc.engine, "pai"), DUE, "pai") > 0


def test_consent_given_again_resumes_and_revises(svc):
    first = run(svc, chosen(1))
    run(svc, chosen(2, **NO_STUDENT))
    r = run(svc, chosen(3, programmes=NEW_PLACES))
    assert (r.status, r.plan_id) == ("revised", first.plan_id)
    row = plan_row(svc, first.plan_id)
    assert row.status == "active"
    assert [p["programme_ref"] for p in row.contract["programmes"]] == ["ovgu-eeit", "btu-artificial-intelligence"]
    assert len(events_of(svc, first.plan_id, "plan_resumed")) == 1
    assert run_reminders(svc.engine, Outbox(svc.engine, "pai"), DUE, "pai") > 0


def test_consent_given_again_same_places_resumes(svc):
    first = run(svc, chosen(1))
    run(svc, chosen(2, **NO_STUDENT))
    r = run(svc, chosen(3))
    assert (r.plan_id) == first.plan_id and plan_row(svc, first.plan_id).status == "active"


def test_held_decision_planned_when_consent_arrives(svc):
    held = run(svc, chosen(1, **NO_STUDENT))
    assert held.status == "held"
    r = run(svc, chosen(2))
    assert (r.status, r.reason) == ("planned", None)
    assert plan_row(svc, r.plan_id).external_ref == "j-sample-1:DE:master"


def test_pause_twice_is_noop(svc):
    first = run(svc, chosen(1))
    run(svc, chosen(2, **NO_STUDENT))
    again = run(svc, chosen(3, **NO_GUARDIAN))
    assert (again.status, again.reason, again.plan_id) == ("paused", "consent_missing", first.plan_id)
    assert len(events_of(svc, first.plan_id, "plan_paused")) == 1
    assert svc.kernel.pause_plan(first.plan_id, "consent_missing") is False
    # the same intake processed again changes nothing more
    store = IntakeStore(svc.engine, "pai")
    process(svc, store.get("d-v3"))
    assert len(events_of(svc, first.plan_id, "plan_paused")) == 1


def test_pause_closed_plan_is_false_and_resume_active_is_false(svc):
    first = run(svc, chosen(1))
    assert svc.kernel.resume_plan(first.plan_id) is False  # not paused
    assert svc.kernel.pause_plan(first.plan_id, "consent_missing") is True
    assert svc.kernel.resume_plan(first.plan_id) is True
    assert svc.kernel.resume_plan(first.plan_id) is False
    svc.kernel.close_plan(first.plan_id, "test")
    assert svc.kernel.pause_plan(first.plan_id, "consent_missing") is False
    assert svc.kernel.resume_plan(first.plan_id) is False


def test_missing_consent_for_new_route_holds_and_keeps_old_plan(svc):
    """No plan on the new route's `external_ref`: the decision is held; the old route's plan is not touched here."""
    first = run(svc, chosen(1))
    r = run(svc, chosen(2, destination_country="NL", **NO_STUDENT))
    assert (r.status, r.reason, r.plan_id) == ("held", "consent_missing", None)
    assert plan_row(svc, first.plan_id).status == "active"


def test_v1_not_authorized_unchanged(svc):
    r = run(svc, v1(authorized_at=None))
    assert (r.status, r.reason, r.plan_id) == ("refused", "not_authorized", None)
    assert intake_rows(svc) == 1
