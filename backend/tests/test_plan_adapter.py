"""P1-T5 Task 5 (R-01, R-04, R-44): with CONNECT_ROADMAP_FROM_PLANVIEW on, the chosen route of a route PAI OS runs is
filled from the OS plan view in today's RoadmapPage.chosen shape; a tick on an OS step completes the OS task; with
CONNECT_CHECKINS_FROM_PLANVIEW the 7-day check-in follows the plan state. The bridge is stubbed: no OS runs here."""

import copy
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import pai_os_bridge as bridge
from app.config import config
from app.models import BackgroundJob, RouteDecision
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap import plan_adapter
from app.pai_c.roadmap.decisions import RouteDecisionService
from tests.test_connect_flags_off import CHOOSE_KEYS
from tests.test_roadmap_api import TOKEN, choose, data, pre_eng

pytestmark = [pytest.mark.req("R-01"), pytest.mark.req("R-04"), pytest.mark.req("R-44")]

STEP_KEYS = {"key", "kind", "label_key", "values", "status", "evidence", "rule", "manual_done", "timing", "colour",
             "tickable", "title"}


def os_step(task_id, key, title, status="pending", owner="student", inbox_kind=None, review=False, **extra):
    return {"task_id": task_id, "instance_key": key, "template_key": key.split("@")[0], "title": title,
            "owner": owner, "status": status, "blocked_reason": None, "inbox_kind": inbox_kind,
            "programme_ref": None, "due_at": None, "due_tz": None, "depends_on": [], "provisional": False,
            "estimated": False, "needs": [], "review": review, **extra}


def view_of(steps, state="active", reason=None, version=1, **extra):
    return {"schema": "pai.plan_view.v1", "student_ref": "x", "state": state, "state_reason": reason, "plan_id": 7,
            "decision_version": version, "revision": 3,
            "route": {"route_key": "r", "origin_country": "PK", "destination_country": "DE", "level": "master",
                      "target_intake": {"term": "winter", "year": 2027}},
            "pages": [], "consent": {"student": "given", "guardian": "not_needed"}, "steps": copy.deepcopy(steps), "requests": [],
            "documents_needed": [], "changes": [{"revision": 2, "at": "2026-11-01T00:00:00Z", "cause": "new_fact",
                                                 "kind": "added", "instance_key": "x"}],
            "proposals_waiting": 2, **extra}


STEPS = [
    os_step(1, "gather@1", "Gather your documents", "waiting_student", inbox_kind="provide",
            due_at="2026-12-01T00:00:00Z", due_tz="Asia/Karachi", estimated=True),
    os_step(2, "apply@1", "Apply to the programme", "pending", inbox_kind="act", provisional=True),
    os_step(3, "check@1", "PAI checks the file", "running", owner="pai"),
    os_step(4, "open@1", "Open the portal", "done", inbox_kind="act"),
    os_step(5, "old@1", "Dropped step", "skipped"),
    os_step(6, "gone@1", "Cancelled step", "cancelled"),
    os_step(7, "pack@1", "Approve your pack", "waiting_student", inbox_kind="approve", review=True),
]


class FakeOs:
    def __init__(self, view):
        self.view, self.completed, self.error, self.reads = view, [], None, 0

    def plan_view(self, ref):
        self.reads += 1
        return None if self.view is None else copy.deepcopy(self.view)

    def complete_step(self, ref, task_id, payload=None):
        if self.error:
            raise bridge.StepError(self.error)
        self.completed.append((ref, task_id))
        for step in self.view["steps"]:
            if step["task_id"] == task_id:
                step["status"] = "done"
        return "done"


@contextmanager
def plan_client(view, *, os_supported=True, roadmap=True, checkins=False, human=True):
    """A signed-in student who chose a route, the flags set, the bridge stubbed with `view`."""
    fake = FakeOs(view)
    with pre_eng() as (client, student, params):
        decision = data(choose(client, params, "electrical_engineering"))
        with student.factory() as db:
            db.query(RouteDecision).one().os_supported = os_supported
            db.commit()
        with patch.object(config, "CONNECT_ROADMAP_FROM_PLANVIEW", roadmap, create=True), \
                patch.object(config, "CONNECT_CHECKINS_FROM_PLANVIEW", checkins, create=True), \
                patch.object(bridge, "counsellor_module_on", lambda: True), \
                patch.object(bridge, "plan_view", fake.plan_view), \
                patch.object(bridge, "complete_step", fake.complete_step), \
                patch("app.routers.roadmap.resolve_human", lambda db, ws, auth: SimpleNamespace() if human else None):
            yield client, student, params, fake, decision


def page(client, params):
    return data(client.get("/v1/roadmap", params=params, headers=TOKEN))["chosen"]


def tick(client, params, key, done=True):
    return client.post("/v1/roadmap/steps", params=params, headers=TOKEN, json={"key": key, "done": done})


def test_chosen_is_filled_from_the_plan_in_todays_shape():
    with plan_client(view_of(STEPS)) as (client, _, params, _fake, _):
        chosen = page(client, params)
    assert set(chosen) == CHOOSE_KEYS | {"plan"}
    assert [s["key"] for s in chosen["steps"]] == ["gather@1", "apply@1", "check@1", "open@1", "pack@1"]
    assert [s["title"] for s in chosen["steps"]][:2] == ["Gather your documents", "Apply to the programme"]
    assert all(set(s) >= STEP_KEYS and s["kind"] == "os" and s["label_key"] == "" and s["values"] == {}
               for s in chosen["steps"])
    assert chosen["steps_done"] == ["open@1"] and chosen["time"] is None
    assert chosen["plan"] == {"state": "active", "state_reason": None, "revision": 3, "decision_version": 1,
                              "proposals_waiting": 2,
                              "changes": [{"revision": 2, "at": "2026-11-01T00:00:00Z", "cause": "new_fact",
                                           "kind": "added", "instance_key": "x"}]}
    first = chosen["steps"][0]
    assert (first["due_at"], first["due_tz"], first["owner"], first["estimated"], first["provisional"]) == (
        "2026-12-01T00:00:00Z", "Asia/Karachi", "student", True, False)
    assert chosen["steps"][1]["provisional"] is True
    assert chosen["live_status"] and chosen["snapshot_steps"] and chosen["route"]  # from the row and the cards


@pytest.mark.parametrize("kernel,shown", [("done", "done"), ("running", "half"), ("ready", "half"),
                                          ("waiting_student", "half"), ("waiting_review", "half"),
                                          ("pending", "not"), ("blocked", "not"), ("failed", "not")])
def test_status_mapping(kernel, shown):
    steps = [os_step(1, "a@1", "A", kernel, owner="pai")]
    with plan_client(view_of(steps)) as (client, _, params, _fake, _):
        [step] = page(client, params)["steps"]
    assert step["status"] == shown and step["colour"] == {"done": "green", "half": "yellow", "not": "red"}[shown]


@pytest.mark.parametrize("owner,status,kind,review,tickable", [
    ("student", "waiting_student", "act", False, True), ("student", "waiting_student", "provide", False, True),
    ("student", "waiting_student", "approve", False, False), ("student", "waiting_student", "choose", False, False),
    ("student", "waiting_student", None, False, False), ("student", "pending", "act", False, False),
    ("pai", "waiting_student", "act", False, False), ("student", "waiting_student", "act", True, False),
    ("student", "done", "act", False, False)])
def test_tickable_rule(owner, status, kind, review, tickable):
    steps = [os_step(1, "a@1", "A", status, owner=owner, inbox_kind=kind, review=review)]
    with plan_client(view_of(steps)) as (client, _, params, _fake, _):
        [step] = page(client, params)["steps"]
    assert step["tickable"] is tickable


def test_a_tick_completes_the_os_task_and_the_page_follows():
    with plan_client(view_of(STEPS)) as (client, student, params, fake, _):
        answer = data(tick(client, params, "gather@1"))
        assert fake.completed == [(student.workspace_id, 1)]
        assert "gather@1" in answer["steps_done"] and answer["plan"]["state"] == "active"
        assert next(s for s in answer["steps"] if s["key"] == "gather@1")["status"] == "done"
        assert page(client, params)["steps_done"] == ["gather@1", "open@1"]
        with student.factory() as db:  # the Counsellor's own ticks are untouched
            assert db.query(RouteDecision).one().steps_done in (None, [])


def test_use_journey_signals_still_work():
    """route_chosen = chosen is truthy; route_step_done = a steps_done key whose step is tickable or done."""
    with plan_client(view_of(STEPS)) as (client, _, params, _fake, _):
        chosen = page(client, params)
    assert chosen
    by_key = {s["key"]: s for s in chosen["steps"]}
    assert any(k in by_key and (by_key[k]["tickable"] or by_key[k]["status"] == "done") for k in chosen["steps_done"])


def test_untick_of_an_os_step_is_refused():
    with plan_client(view_of(STEPS)) as (client, _, params, fake, _):
        refused = tick(client, params, "open@1", done=False)
    assert refused.status_code == 409 and "cannot be undone" in refused.json()["detail"]
    assert fake.completed == []


def test_a_review_step_is_refused_and_a_pai_step_too():
    with plan_client(view_of(STEPS)) as (client, _, params, fake, _):
        review = tick(client, params, "pack@1")
        pai = tick(client, params, "check@1")
        unknown = tick(client, params, "nope@1")
    assert review.status_code == 409 and "approve" in review.json()["detail"].lower()
    assert pai.status_code == 409 and unknown.status_code == 422
    assert fake.completed == []


def test_a_token_only_caller_cannot_tick_an_os_step():
    with plan_client(view_of(STEPS), human=False) as (client, _, params, fake, _):
        refused = tick(client, params, "gather@1")
        everything = [tick(client, params, k, done) for k, done in (("pack@1", True), ("check@1", True),
                                                                    ("open@1", False), ("apply@1", True))]
        assert page(client, params)["steps_done"] == ["open@1"]  # reading needs no account
    assert refused.status_code == 403 and "account" in refused.json()["detail"]
    assert [r.status_code for r in everything] == [403] * 4
    assert fake.completed == []


@pytest.mark.parametrize("code,status", [("not_found", 404), ("not_yours", 404), ("not_waiting", 409),
                                         ("review_required", 409), ("unavailable", 503)])
def test_os_refusals_become_http_statuses(code, status):
    with plan_client(view_of(STEPS)) as (client, _, params, fake, _):
        fake.error = code
        assert tick(client, params, "gather@1").status_code == status


def test_the_empty_state_keeps_todays_view_and_says_so():
    with plan_client(view_of([], state="empty", plan_id=None, decision_version=None, revision=None, route=None,
                             consent=None, changes=[], proposals_waiting=0), roadmap=False) as (client, _, params, fake, _):
        today = page(client, params)
        assert "plan" not in today
        with patch.object(config, "CONNECT_ROADMAP_FROM_PLANVIEW", True, create=True):
            empty = page(client, params)
    assert empty.pop("plan") == {"state": "empty"} and empty == today
    assert empty["steps"] and all(s["kind"] != "os" for s in empty["steps"])


def test_a_plan_of_an_older_choice_is_not_shown_for_a_new_route():
    """The OS holds version 1 of another route; the row is version 2: not applied yet, so the empty state."""
    stale = view_of(STEPS, version=1)
    stale["route"]["destination_country"] = "FR"
    with plan_client(stale) as (client, student, params, _fake, _):
        with student.factory() as db:
            row = db.query(RouteDecision).one()
            row.destination_country, row.level, row.origin_country, row.decision_version = "DE", "master", "PK", 2
            db.commit()
        chosen = page(client, params)
    assert chosen["plan"] == {"state": "empty"} and all(s["kind"] != "os" for s in chosen["steps"])


def test_the_plan_is_read_once_per_request():
    with plan_client(view_of(STEPS)) as (client, student, params, fake, _):
        fake.reads = 0
        page(client, params)
        assert fake.reads == 1
        fake.reads = 0
        data(tick(client, params, "gather@1"))
        assert fake.reads == 2  # once to check the tick, once after it for the answer
        with student.factory() as db:
            from app.pai_c.roadmap.decisions import RouteDecisionService
            fake.reads = 0
            assert RouteDecisionService(db).current(student.workspace_id)["plan"]["state"] == "active"
            assert fake.reads == 1
    with plan_client(view_of([], state="empty", plan_id=None, decision_version=None, revision=None, route=None,
                             consent=None, changes=[], proposals_waiting=0)) as (client, _, params, fake, _):
        fake.reads = 0
        data(tick(client, params, "apply"))  # an empty plan: the Counsellor's own tick, one read
        assert fake.reads == 1


def test_os_steps_say_who_owns_them():
    with plan_client(view_of(STEPS)) as (client, _, params, _fake, _):
        owners = {s["key"]: s["owner"] for s in page(client, params)["steps"]}
    assert owners["gather@1"] == "student" and owners["check@1"] == "pai"


DETAILS = ChoiceDetails(origin_country="PK", destination_country="DE", level="master", places=(), intake=None)


def test_a_rechosen_route_does_not_show_the_stopped_plan_of_the_withdrawn_choice():
    """Choose, withdraw, choose the same route again while the OS still shows the old plan, stopped, at version 1."""
    stopped = view_of(STEPS, state="stopped", reason="withdrawn", version=1)
    with plan_client(stopped, checkins=True) as (client, student, params, _fake, _):
        data(client.post("/v1/roadmap/withdraw", params=params, headers=TOKEN))
        with student.factory() as db, patch.object(bridge, "route_supported", lambda *a: True):
            answer = RouteDecisionService(db).choose(student.workspace_id, "electrical_engineering", DETAILS)
            db.commit()
        assert answer["plan"] == {"state": "empty"} and all(s["kind"] != "os" for s in answer["steps"])
        chosen = page(client, params)
        assert chosen["plan"] == {"state": "empty"} and all(s["kind"] != "os" for s in chosen["steps"])
        with student.factory() as db:
            row = db.query(RouteDecision).filter(RouteDecision.withdrawn_at.is_(None)).one()
            assert row.decision_version == 3 and plan_adapter.plan_superseded(row) is False


def test_a_finished_old_plan_is_not_applied_to_a_newer_choice_of_the_same_route():
    row = SimpleNamespace(decision_version=2, origin_country="PK", destination_country="DE", level="master")
    live = view_of(STEPS, version=1)
    assert plan_adapter.applied(row, live) is True  # a consent change: same route, plan still live
    assert plan_adapter.applied(row, view_of(STEPS, state="finished", version=1)) is False
    live["route"]["origin_country"] = "IN"
    assert plan_adapter.applied(row, live) is False


def test_a_stopped_plan_is_shown_with_its_reason():
    with plan_client(view_of(STEPS, state="stopped", reason="withdrawn")) as (client, _, params, _fake, _):
        chosen = page(client, params)
    assert chosen["plan"]["state"] == "stopped" and chosen["plan"]["state_reason"] == "withdrawn"


def test_a_row_the_os_does_not_run_keeps_todays_view_and_asks_nothing():
    with plan_client(view_of(STEPS), os_supported=False) as (client, _, params, fake, _):
        with patch.object(bridge, "plan_view", side_effect=AssertionError("asked the OS")):
            chosen = page(client, params)
        refused = tick(client, params, "gather@1")
    assert "plan" not in chosen and all(s["kind"] != "os" for s in chosen["steps"])
    assert refused.status_code == 422 and fake.completed == []


def test_an_os_that_cannot_answer_keeps_todays_view():
    with plan_client(None) as (client, _, params, _fake, _):
        chosen = page(client, params)
    assert "plan" not in chosen and all(s["kind"] != "os" for s in chosen["steps"])


def test_an_os_that_cannot_answer_refuses_a_tick_with_503_and_ticks_nothing_locally():
    with plan_client(None) as (client, student, params, fake, _):
        refused = tick(client, params, "apply")  # a legacy step key: must not fall through to a local tick
        assert page(client, params)["steps_done"] == []
        with student.factory() as db:
            assert db.query(RouteDecision).one().steps_done in (None, [])
    assert refused.status_code == 503 and fake.completed == []


def test_flag_on_then_off_shows_todays_view():
    with plan_client(view_of(STEPS)) as (client, _, params, _fake, _):
        on = page(client, params)
        with patch.object(config, "CONNECT_ROADMAP_FROM_PLANVIEW", False, create=True):
            with patch.object(bridge, "plan_view", side_effect=AssertionError("asked the OS")):
                off = page(client, params)
    assert on["steps"][0]["kind"] == "os" and "plan" in on
    assert "plan" not in off and set(off) == CHOOSE_KEYS
    assert [s["kind"] for s in off["steps"]][0] != "os" and off["steps_done"] == []


# ---- the 7-day check-in -------------------------------------------------------------------------------------------

async def run_checkin(student):
    from app.pai_c.checkins import checkin_job
    with student.factory() as db:
        job = db.query(BackgroundJob).filter(BackgroundJob.job_type == "counselor.checkin").one()
        return await checkin_job(job, db)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["stopped", "finished"])
async def test_a_stopped_or_finished_plan_supersedes_the_checkin(state):
    with plan_client(view_of(STEPS, state=state, reason="withdrawn" if state == "stopped" else None),
                     checkins=True) as (_, student, _p, _fake, _):
        assert await run_checkin(student) == {"status": "superseded"}


@pytest.mark.asyncio
async def test_a_checkin_flag_off_ignores_the_plan_state():
    with plan_client(view_of(STEPS, state="stopped", reason="withdrawn"), checkins=False) as (_, student, _p, _f, _):
        with patch.object(bridge, "plan_view", side_effect=AssertionError("asked the OS")):
            assert (await run_checkin(student)) != {"status": "superseded"}


@pytest.mark.asyncio
async def test_a_live_plan_keeps_the_checkin():
    with plan_client(view_of(STEPS, state="needs_student"), checkins=True) as (_, student, _p, _f, _):
        assert (await run_checkin(student)) != {"status": "superseded"}


@pytest.mark.asyncio
async def test_a_checkin_for_a_row_the_os_does_not_run_ignores_the_plan():
    with plan_client(view_of(STEPS, state="stopped", reason="withdrawn"), checkins=True,
                     os_supported=False) as (_, student, _p, _f, _):
        assert (await run_checkin(student)) != {"status": "superseded"}
