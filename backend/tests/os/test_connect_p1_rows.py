# ruff: noqa: F811
"""P1-T10 Task B1 (R-04, R-44, R-45): rows of master section 6 that no flow proves yet, and the lifecycle rows on all
four fictional routes, each delivered by ONE sweep only. The after-commit delivery of the roadmap route is switched off
(`only_the_sweep`), so a change reaches PAI OS exactly when `bridge.sweep_once` runs: that is "within one sweep".

Rows here: 6.1 6.2 6.3 6.4 6.11 on the four routes (Germany master's, fake Pakistan BS, fake Ireland master's, fake
Pakistan intermediate); 6.9 constraints (exclusion, field order, budget, domicile, place preference); 6.18 plan
finished (read as: a notification, the roadmap shows "finished", the check-in ends, no new journey stage - Q6).
Fictional students and programmes only. No model call."""

from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.os import models
from app.os.adapters.counsellor.store import IntakeStore
from app.os.knowledge.programmes import Programme, ProgrammeStore
from tests.os.test_connect_t4_flow import (  # noqa: F401
    ENTRY_TYPE,
    NOW,
    Queue,
    host_facts,
    os_world,
    run_rules,
    vault_rows,
    write,
)
from tests.os.test_connect_t5_flow import (  # noqa: F401
    bell,
    chosen,
    germany_student,
    level,
    no_chat,
    row_counts,
    run_os,
    svc,
    world,
)
from tests.test_roadmap_api import data
from tests.test_roadmap_choice_api import choose_with, post, vault

pytestmark = [pytest.mark.req("R-04"), pytest.mark.req("R-44"), pytest.mark.req("R-45")]

WINTER = {"term": "winter", "year": 2027}


@dataclass(frozen=True)
class Route:
    name: str
    destination: str
    level: str
    places: tuple[str, str]


GERMANY = Route("germany_master", "DE", "master", ("ovgu-eeit", "btu-artificial-intelligence"))
PK_BS = Route("fake_pakistan_bs", "PK", "bachelor", ("pk-p1", "pk-p2"))
IRELAND = Route("fake_ireland_master", "IE", "master", ("ie-p1", "ie-p2"))
PK_INTER = Route("fake_pakistan_intermediate", "PK", "intermediate", ("pk-i1", "pk-i2"))
# the route each lifecycle moves to in row 6.3: another destination, a level change, and a new country again
MOVES = {GERMANY: IRELAND, PK_BS: GERMANY, IRELAND: PK_BS, PK_INTER: PK_BS}
ROUTES = list(MOVES)
IDS = [r.name for r in ROUTES]


@pytest.fixture
def lane(world):
    """The T5 world with a second fake programme on each Pakistan route, so places can be added and reordered."""
    store = ProgrammeStore(world.engine, "pai")
    for ref, route in (("pk-p2", "pakistan_bs"), ("pk-i2", "pakistan_inter")):
        store.upsert(Programme(ref=ref, route_key=route, university="University", name=f"Programme {ref}", aliases=(),
                               start_urls=(f"https://example.org/{ref}",), official_domains=("example.org",)))
    return world


class _Bridge:
    """The bridge as the roadmap route sees it, without the after-commit delivery: a change reaches PAI OS only when
    the sweep runs."""

    def __getattr__(self, name):
        return getattr(bridge, name)

    @staticmethod
    def deliver_pending(db, workspace_id=None):
        return {"delivered": 0, "failed": 0, "not_sent": 0}


@contextmanager
def only_the_sweep():
    with patch("app.routers.roadmap.pai_os_bridge", _Bridge()):
        yield


def sweep(svc_, who) -> list[tuple[str, str | None]]:
    """One sweep, the OS intake it feeds, and one delivery of the OS events that raised. Returns the intake results."""
    with who.factory() as db:
        bridge.sweep_once(db)
    done = run_os(svc_)
    with who.factory() as db:
        bridge.deliver_os_events(db)
    return done


def waiting(svc_, who) -> int:
    return len(IntakeStore(svc_.engine, "pai").pending())


def choose(client, params, route: Route, refs=None):
    refs = refs or route.places[:1]
    return data(choose_with(client, params, destination=route.destination, intake=WINTER,
                            places=[{"ref": r, "rank": i + 1} for i, r in enumerate(refs)]))


def same_in_both(client, params, who) -> dict:
    """The roadmap's chosen route and the OS plan view show the same version, state and steps."""
    from app.pai_c.roadmap.plan_adapter import STATUS

    page, view = chosen(client, params), bridge.plan_view(who.workspace_id)
    assert view is not None and page["plan"]["state"] == view["state"]
    assert page["plan"]["decision_version"] == view["decision_version"] and page["plan"]["revision"] == view["revision"]
    shown = {s["key"]: s["status"] for s in page["steps"]}
    held = {s["instance_key"]: STATUS[s["status"]] for s in view["steps"] if s["status"] in STATUS}
    assert shown == held and shown
    return page


def plans_of(svc_, who) -> list:
    with svc_.engine.connect() as conn:
        return list(conn.execute(select(models.plans.c.id, models.plans.c.status, models.plans.c.contract)
                                 .where(models.plans.c.student_ref == who.workspace_id).order_by(models.plans.c.id)))


def tick(svc_, client, params, who, page) -> dict:
    """Row 6.11. A tick on a tickable step from the roadmap, or, on a route without one, the step PAI itself finishes
    (the kernel's own result): either way it is done on both sides, and the roadmap is not asked to say so."""
    from sqlalchemy import update

    from app.os.kernel.kernel import Outcome

    view = bridge.plan_view(who.workspace_id)
    step = next((s for s in page["steps"] if s["tickable"]), None)
    if step is not None:
        ticked = data(post(client, params, "steps", {"key": step["key"], "done": True}))
        assert {s["key"]: s["status"] for s in ticked["steps"]}[step["key"]] == "done"
    else:
        step = next(s for s in page["steps"] if s["status"] != "done")
        task_id = {v["instance_key"]: v["task_id"] for v in view["steps"]}[step["key"]]
        with svc_.engine.begin() as conn:
            conn.execute(update(models.tasks).where(models.tasks.c.id == task_id).values(state="ready", attempt=1))
        assert svc_.kernel.mark_running(task_id, 1)
        svc_.kernel.apply_result(task_id, 1, Outcome("done"))
    assert {s["instance_key"]: s["status"] for s in bridge.plan_view(who.workspace_id)["steps"]}[step["key"]] == "done"
    assert step["key"] in chosen(client, params)["steps_done"]
    return step


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
@pytest.mark.connect_row("6.1", "6.2", "6.3", "6.4", "6.11")
def test_the_lifecycle_of_a_choice_on_each_route_within_one_sweep_each(lane, route):
    svc_ = lane
    away = MOVES[route]
    with germany_student() as (client, who, params), only_the_sweep():
        with level(route.level):
            vault((client, who, params))
            before = row_counts(who)

            # 6.1 choose: nothing reaches the OS until the sweep; then the plan is v1 and the roadmap shows it
            body = choose(client, params, route)
            assert body["choice"]["os_supported"] is True and waiting(svc_, who) == 0
            assert chosen(client, params)["plan"] == {"state": "empty"}
            assert sweep(svc_, who) == [("planned", None)]
            page = same_in_both(client, params, who)
            assert page["plan"]["decision_version"] == 1 and {s["kind"] for s in page["steps"]} == {"os"}
            assert [kind for kind, _ in bell(who)].count("plan_created") == 1

            # 6.11 a tick on a tickable step: done on both sides (the tick is the kernel's, not a copy)
            step = tick(svc_, client, params, who, page)
            same_in_both(client, params, who)

            # 6.2 places added, then reordered: revised at v2 and v3, the done step stays done, what changed is shown
            choose(client, params, route, list(route.places))
            assert waiting(svc_, who) == 0 and chosen(client, params)["plan"]["decision_version"] == 1
            assert sweep(svc_, who) == [("revised", None)]
            page = same_in_both(client, params, who)
            assert page["plan"]["decision_version"] == 2 and page["plan"]["changes"]
            assert step["key"] in page["steps_done"]
            choose(client, params, route, list(reversed(route.places)))
            assert sweep(svc_, who) == [("revised", None)]
            page = same_in_both(client, params, who)
            assert page["plan"]["decision_version"] == 3 and step["key"] in page["steps_done"]
            (old,) = plans_of(svc_, who)

        # 6.3 a change of destination or level: the old plan is closed, a new plan exists, the roadmap shows the new
        with level(away.level):
            choose(client, params, away)
            assert [p.status for p in plans_of(svc_, who)] == [old.status]  # not before the sweep
            assert sweep(svc_, who) == [("replaced", None)]
            old_row, new_row = plans_of(svc_, who)
            assert old_row.id == old.id and old_row.status == "closed" and new_row.status != "closed"
            assert new_row.contract["destination_country"] != old_row.contract["destination_country"] or \
                new_row.contract["level"] != old_row.contract["level"]
            page = same_in_both(client, params, who)
            assert page["plan"]["decision_version"] == 4
            assert bridge.plan_view(who.workspace_id)["route"]["level"] == away.level

            # 6.4 withdraw: the plan is stopped and the roadmap is back to choosing
            data(post(client, params, "withdraw"))
            assert plans_of(svc_, who)[-1].status != "closed" and waiting(svc_, who) == 0
            assert sweep(svc_, who) == [("withdrawn", None)]
            assert [p.status for p in plans_of(svc_, who)] == ["closed", "closed"]
            assert bridge.plan_view(who.workspace_id)["state"] == "stopped"
            assert chosen(client, params) is None or chosen(client, params).get("steps") in (None, [])
            assert "plan_stopped" in [kind for kind, _ in bell(who)]
            no_chat(who, before)


# --- row 6.18: plan finished ---------------------------------------------------------------------------------------

def walk_to_done(svc_, plan_id: int, student_ref: str) -> None:
    """Every task of the plan done through the kernel: the student's own with their completion, PAI's work with its
    result (a task that waits for anything else is made ready first, as the T5 flow does for the step it finishes)."""
    from sqlalchemy import update

    from app.os.kernel.kernel import Outcome

    T = models.tasks
    for _ in range(200):
        with svc_.engine.connect() as conn:
            left = conn.execute(select(T.c.id, T.c.kind, T.c.state, T.c.attempt).where(
                T.c.plan_id == plan_id, T.c.state.not_in(("done", "skipped", "cancelled"))).order_by(T.c.id)).all()
        if not left:
            return
        t = left[0]
        if t.kind == "student" and t.state == "waiting_student":
            svc_.kernel.complete_student_task(t.id, student_ref, {})
            continue
        with svc_.engine.begin() as conn:
            conn.execute(update(T).where(T.c.id == t.id).values(state="ready", attempt=max(t.attempt, 1)))
        if t.kind == "student":
            with svc_.engine.begin() as conn:
                conn.execute(update(T).where(T.c.id == t.id).values(state="waiting_student"))
            svc_.kernel.complete_student_task(t.id, student_ref, {})
        else:
            assert svc_.kernel.mark_running(t.id, max(t.attempt, 1))
            svc_.kernel.apply_result(t.id, max(t.attempt, 1), Outcome("done"))
    raise AssertionError("the plan did not finish")


@pytest.mark.connect_row("6.18")
def test_a_finished_plan_is_one_notice_shows_finished_ends_the_checkin_and_adds_no_stage(lane):
    from app.models import RouteDecision, StudentJourney
    from app.pai_c.roadmap import plan_adapter

    svc_ = lane
    with germany_student() as (client, who, params), only_the_sweep(), level("master"), \
            patch.object(plan_adapter, "part_on", lambda name: True):
        vault((client, who, params))
        choose(client, params, GERMANY)
        assert sweep(svc_, who) == [("planned", None)]
        before = row_counts(who)
        with who.factory() as db:
            journey = db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == who.workspace_id))
            stage_before = journey.current_stage
            row = db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == who.workspace_id))
            assert plan_adapter.plan_superseded(row) is False  # a running plan keeps its check-in
        plan_id = plans_of(svc_, who)[0].id
        notices = len(bell(who))

        walk_to_done(svc_, plan_id, who.workspace_id)
        assert plans_of(svc_, who)[0].status == "done"
        with svc_.engine.connect() as conn:
            kinds = conn.execute(select(models.events.c.type).where(
                models.events.c.plan_id == plan_id, models.events.c.type == "plan_finished")).scalars().all()
        assert len(kinds) == 1

        assert sweep(svc_, who) == []  # the OS event reaches the app with the sweep, once
        with who.factory() as db:
            bridge.sweep_once(db)  # a repeat sweep adds nothing
        assert [k for k, _ in bell(who)[notices:]].count("plan_finished") == 1
        page = same_in_both(client, params, who)
        assert page["plan"]["state"] == "finished" and page["steps_done"]
        with who.factory() as db:
            row = db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == who.workspace_id))
            assert plan_adapter.plan_superseded(row) is True  # the check-in follow-up ends
            journey = db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == who.workspace_id))
            assert journey.current_stage == stage_before  # no new journey stage (Q6; R-45)
        no_chat(who, before)


# --- row 6.9: a constraint changes (fake Pakistan BS: the merit seed of the T4 flow) -----------------------------------

CONSTRAINTS = {  # case -> (Vault write, the StudentFacts key it touches)
    "field_order": (("vault_item", "field_order", {"fields": ["Pharm-D", "Computer Science"]}), "constraint.field_order"),
    "budget": (("vault_fact", "finance.budget", {"band": "1_3_lakh"}), "constraint.budget"),
    "domicile": (("vault_item", "domicile", {"province": "punjab", "area": "urban"}), "constraint.domicile"),
    "place_preference": (("vault_item", "place_preference", {"scope": "abroad", "fallback": "none", "regions": []}),
                         "preference.place"),
}


def start_pk_plan(os_world, db, ws) -> int:
    from app.os import ports
    from app.os.contracts.route_contract import RouteContract
    from app.os.eligibility import facts as eligibility_facts
    from app.os.eligibility.facts import current_types

    ports.configure(os_world.svc, student_facts=lambda ref: host_facts.build(db, ref))
    eligibility_facts.configure_types(current_types() | {"entry_test": ENTRY_TYPE})
    plan_id = os_world.svc.plans.start_plan(RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{ws}", "student_ref": ws,
        "origin_country": "PK", "destination_country": "PK", "level": "bachelor",
        "target_intake": WINTER, "programmes": [{"programme_ref": "p-easy", "rank": 1},
                                                {"programme_ref": "p-hard", "rank": 2}]})).plan_id
    write(db, ws, "student_record", "education",
          {"qualification_name": "FSc", "institution_name": "A College", "academic_status": "completed",
           "result": {"marks_obtained": 1000, "marks_total": 1100}})
    write(db, ws, "student_record", "test_attempt", {"test_type": "entry_test", "overall_score": "80"})
    assert bridge.sweep_once(db)["submitted"] == 2
    return plan_id


def places_of(os_world, plan_id) -> list[str]:
    return [p.programme_ref for p in os_world.svc.plans._contract(plan_id)[0].programmes]


def fact_events(engine, plan_id) -> list[dict]:
    with engine.connect() as conn:
        return list(conn.execute(select(models.events.c.payload).where(
            models.events.c.type == "student_fact_changed", models.events.c.plan_id == plan_id)
            .order_by(models.events.c.id)).scalars())


@pytest.mark.parametrize("case", list(CONSTRAINTS))
@pytest.mark.connect_row("6.9")
def test_a_changed_constraint_is_one_event_one_sweep_and_never_a_silent_removal(os_world, case):
    from app.config import config
    from app.os.replan.run import run_replan_job
    from scripts.counselor_eval_support import StudentSession

    (kind, key, value), fact_key = CONSTRAINTS[case]
    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True):
        ws = student.workspace_id
        plan_id = start_pk_plan(os_world, db, ws)
        assert run_rules(os_world, plan_id) is not None
        seen, places = len(fact_events(os_world.engine, plan_id)), places_of(os_world, plan_id)
        rows = len(vault_rows(db, ws))

        write(db, ws, kind, key, value)
        (row,) = vault_rows(db, ws)[rows:]  # one Vault write: one event, listing only the key it touched
        assert row.status == "pending" and row.payload["keys"] == [fact_key]
        assert len(fact_events(os_world.engine, plan_id)) == seen  # the OS has heard nothing yet
        assert bridge.sweep_once(db)["submitted"] == 1  # one sweep
        got = fact_events(os_world.engine, plan_id)
        assert len(got) == seen + 1 and got[-1]["keys"] == [fact_key] and got[-1]["vault_version"] == row.payload["vault_version"]
        queue = Queue()
        assert run_replan_job(os_world.replanner, queue, NOW) == 1  # the replan is queued for the plan
        run_rules(os_world, plan_id)
        assert places_of(os_world, plan_id) == places  # nothing removed by itself
        assert os_world.replanner.proposals.pending_for(ws) == []
        assert bridge.sweep_once(db)["submitted"] == 0


def excluded_world(os_world, student, db):
    """A student with one open path (Pharm-D) and a plan; returns (path row, plan id)."""
    from tests.test_path_exclusions import add_path, setup

    _, journey = setup(student, db)
    row = add_path(db, student, journey, "pharm_d")
    return row, start_pk_plan(os_world, db, student.workspace_id)


@pytest.mark.connect_row("6.9")
def test_an_excluded_field_leaves_every_counsellor_reader_at_once_and_reaches_the_os_in_one_sweep(os_world):
    from app.config import config
    from app.main import app
    from app.pai_c.journey_sync import _live_paths
    from app.pai_c.possibilities import PossibilityService
    from app.pai_c.roadmap.engine import RoadmapEngine
    from scripts.counselor_eval_support import StudentSession
    from tests.counselor_fixtures import client_for

    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True):
        ws = student.workspace_id
        row, plan_id = excluded_world(os_world, student, db)
        seen, places, rows = len(fact_events(os_world.engine, plan_id)), places_of(os_world, plan_id), len(vault_rows(db, ws))
        client = client_for(student)
        try:
            assert [c["possibility_id"] for c in RoadmapEngine(db).build(ws)["fields"]] == [row.id]
            pressed = client.post(f"/v1/counselor/possibilities/{row.id}/dismiss?network={ws}",
                                  headers={"X-Workspace-Token": "synthetic-test-only"})
            assert pressed.status_code == 200
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        # the same request cycle: paths, chat cards (the possibilities reader), the roadmap and the live-path check
        assert PossibilityService(db).current(ws) == []
        assert RoadmapEngine(db).build(ws)["fields"] == [] and _live_paths(db, ws) is False
        # one Vault event for the OS, and one sweep brings it there
        new = vault_rows(db, ws)[rows:]
        assert [r.payload["keys"] for r in new] == [["constraint.excluded_fields"]]
        assert len(fact_events(os_world.engine, plan_id)) == seen
        assert bridge.sweep_once(db)["submitted"] == 1
        assert [e["keys"] for e in fact_events(os_world.engine, plan_id)[seen:]] == [["constraint.excluded_fields"]]
        assert places_of(os_world, plan_id) == places and os_world.replanner.proposals.pending_for(ws) == []


@pytest.mark.connect_row("6.9")
@pytest.mark.xfail(strict=True, reason="Q4 (owner ruling 2026-11-07): the OS side of R-15 moves to P2. The OS programme "
                   "list has no field tag, so an excluded field raises no proposal; the nightly job opens a case instead "
                   "(rule 8). When P2 builds it, this test starts to pass and strict xfail makes that visible.")
def test_an_excluded_chosen_field_raises_a_proposal_on_the_plan_P2(os_world):
    from app.config import config
    from scripts.counselor_eval_support import StudentSession

    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True):
        ws = student.workspace_id
        _, plan_id = excluded_world(os_world, student, db)
        write(db, ws, "vault_item", "option", {"text": "Pharm-D", "status": "ruled_out"})
        assert bridge.sweep_once(db)["submitted"] >= 1
        run_rules(os_world, plan_id)
        assert os_world.replanner.proposals.pending_for(ws) != []


@pytest.mark.connect_row("6.9")
def test_an_excluded_field_leaves_the_stage_h_list(os_world):
    from app.config import config
    from app.models import ExecutionRun
    from app.pai_c.connect import places
    from app.pai_c.paths import exclusions
    from scripts.counselor_eval_support import StudentSession

    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True):
        ws = student.workspace_id
        row, _ = excluded_world(os_world, student, db)
        db.add(ExecutionRun(workspace_id=ws, requested_by="openagents:pai", objective="programs", status="completed",
                            task_type="program_search", constraints={"possibility_id": row.id},
                            result={"capability_result": {"programs": [{"opportunity_id": "opp-1"}]}}))
        db.commit()
        listed = {"programs": [{"opportunity_id": "opp-1", "title": "Programme", "country": "Pakistan"}]}
        with patch("app.pai_c.paths.programs.current_programs", return_value=(listed, False)):
            assert [p["opportunity_id"] for p in places._stage_h_programs(db, ws)] == ["opp-1"]
            write(db, ws, "vault_item", "option", {"text": exclusions.field_label("pharm_d"), "status": "ruled_out"})
            assert list(exclusions.excluded_fields(db, ws)) == ["pharm_d"]
            assert places._stage_h_programs(db, ws) == []
