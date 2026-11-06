"""P1-T6 Task 4 (R-11, D-x7, D-x8): after the Counsellor took an escalation, the host pauses the student's plan with
the reason code; only a changed choice lifts that pause, a consent copy or the same choice again does not; a
`consent_missing` pause resumes as before. Fictional exports from app/os/contracts/samples/v2."""

import pytest
from sqlalchemy import select

from app.os import ports
from app.os.adapters.counsellor.store import IntakeStore
from app.os.ports import plan_source
from app.os.plan_view import build_plan_view
from test_counsellor_intake_v2 import NEW_PLACES, P, chosen, plan_row, run, svc  # noqa: F401

pytestmark = pytest.mark.req("R-11")

STUDENT = "ws-sample-1"
NO_STUDENT = {"authorized_at": None}


@pytest.fixture(autouse=True)
def mounted(svc):  # noqa: F811
    ports.configure(svc)
    yield
    ports.configure(None)


def apply(svc, n: int, **over):  # noqa: F811
    """Runs version n through intake and records it as applied, like the worker does."""
    export = chosen(n, **over)
    result = run(svc, export)
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get(export["decision_id"]).id, result.status, result.reason, result.plan_id)
    return result


def view(svc):  # noqa: F811
    return build_plan_view(svc, STUDENT)


def test_plan_paused_with_reason_code(svc):  # noqa: F811
    first = apply(svc, 1)
    assert plan_source.pause_for_escalation(STUDENT, 1, "not_eligible") is True
    assert plan_row(svc, first.plan_id).status == "paused"
    got = view(svc)
    assert (got.state, got.state_reason) == ("paused", "not_eligible")


def test_pause_names_a_version_that_is_not_the_plans_newest_does_nothing(svc):  # noqa: F811
    first = apply(svc, 1)
    apply(svc, 2, programmes=NEW_PLACES)
    assert plan_source.pause_for_escalation(STUDENT, 1, "all_rejected") is False
    assert plan_row(svc, first.plan_id).status == "active"
    assert plan_source.pause_for_escalation(STUDENT, 2, "all_rejected") is True


def test_no_plan_no_pause(svc):  # noqa: F811
    assert plan_source.pause_for_escalation(STUDENT, None, "other") is False


def test_a_closed_plan_is_not_paused(svc):  # noqa: F811
    first = apply(svc, 1)
    svc.kernel.close_plan(first.plan_id, "withdrawn")
    assert plan_source.pause_for_escalation(STUDENT, None, "other") is False


def test_consent_copy_keeps_escalation_pause(svc):  # noqa: F811
    first = apply(svc, 1)
    plan_source.pause_for_escalation(STUDENT, 1, "deadline_passed")
    r = apply(svc, 2, authorized_at="2027-01-12T09:00:05+05:00")  # same choice, renewed consent
    assert (r.status, r.plan_id) == ("revised", first.plan_id)
    assert plan_row(svc, first.plan_id).status == "paused"
    assert view(svc).state_reason == "deadline_passed"


def test_same_rechoice_keeps_pause(svc):  # noqa: F811
    first = apply(svc, 1)
    plan_source.pause_for_escalation(STUDENT, 1, "blocking_gap")
    apply(svc, 2)  # the student chose the very same places again
    assert plan_row(svc, first.plan_id).status == "paused"


def test_changed_choice_resumes(svc):  # noqa: F811
    first = apply(svc, 1)
    plan_source.pause_for_escalation(STUDENT, 1, "all_rejected")
    r = apply(svc, 2, programmes=NEW_PLACES)
    assert (r.status, r.plan_id) == ("revised", first.plan_id)
    row = plan_row(svc, first.plan_id)
    assert row.status == "active" and [p["programme_ref"] for p in row.contract["programmes"]] == [
        "ovgu-eeit", "btu-artificial-intelligence"]
    assert view(svc).state != "paused"


def test_changed_order_or_intake_resumes(svc):  # noqa: F811
    first = apply(svc, 1)
    plan_source.pause_for_escalation(STUDENT, 1, "not_eligible")
    swapped = [{"programme_ref": "ovgu-eeit", "rank": 1}, {"programme_ref": "tu-chemnitz-embedded-systems", "rank": 2}]
    apply(svc, 2, programmes=swapped)
    assert plan_row(svc, first.plan_id).status == "active"
    plan_source.pause_for_escalation(STUDENT, 2, "other")
    apply(svc, 3, programmes=swapped, target_intake={"term": "summer", "year": 2028})
    assert plan_row(svc, first.plan_id).status == "active"


def test_consent_pause_resumes_as_today(svc):  # noqa: F811
    first = apply(svc, 1)
    r = apply(svc, 2, **NO_STUDENT)
    assert (r.status, r.reason) == ("paused", "consent_missing")
    assert plan_row(svc, first.plan_id).status == "paused"
    back = apply(svc, 3)  # the same choice, the consent given again
    assert back.plan_id == first.plan_id and plan_row(svc, first.plan_id).status == "active"


def test_withdrawn_consent_over_an_escalation_pause_stays_until_the_choice_changes(svc):  # noqa: F811
    first = apply(svc, 1)
    plan_source.pause_for_escalation(STUDENT, 1, "all_rejected")
    apply(svc, 2, **NO_STUDENT)  # already paused: the escalation reason stays
    assert view(svc).state_reason == "all_rejected"
    apply(svc, 3)  # consent back, same choice
    assert plan_row(svc, first.plan_id).status == "paused"
