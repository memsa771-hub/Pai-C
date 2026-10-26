"""The journey stage follows the route decision (ROADMAP_ENGINE_SPEC.md §3).

The engine computes routes on read, so there is no research wait: a confirmed
Mirror goes straight to PROPOSED, choosing a route moves to CHOSEN, withdrawing
goes back to PROPOSED, and chat `rethink` moves only the stage. Every test
starts from a real Mirror confirmation, not a forced stage.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import BackgroundJob, PaiPossibility, RouteDecision, StudentJourney
from app.pai_c.deep.mirror import JOB_RESEARCH, confirmed_research_job
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_mirror import client_for, draft_ready
from tests.test_roadmap_engine import add_education, add_path, field_title, fsc

TOKEN = {"X-Workspace-Token": "synthetic-test-only"}


@asynccontextmanager
async def confirmed_student():
    """A student whose Mirror was confirmed through the API and whose
    confirmation job ran, plus an education record and two field paths."""
    with StudentSession() as student, student.factory() as db:
        journey = draft_ready(student, db)
        client = client_for(student)
        try:
            response = client.post("/v1/counselor/summary/confirm", params={"network": student.workspace_id},
                                   json={"version": 1}, headers=TOKEN)
            assert response.status_code == 200, response.text
            db.expire_all()
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == JOB_RESEARCH))
            assert (await confirmed_research_job(job, db))["status"] == "done"
            yield client, student, db, journey.id
        finally:
            app.dependency_overrides.pop(get_db, None)


def stage(db, journey_id):
    db.expire_all()
    return db.get(StudentJourney, journey_id).current_stage


def with_routes(student, db):
    add_education(student, db, fsc("pre_engineering", 78))
    for key in ("electrical_engineering", "computer_engineering"):
        add_path(student, db, field_title(key), key)


def choose(client, student, field_key):
    response = client.post("/v1/roadmap/choose", params={"network": student.workspace_id}, headers=TOKEN,
                           json={"field_key": field_key})
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_mirror_confirmation_creates_paths_and_proposes():
    async with confirmed_student() as (_, student, db, journey_id):
        assert stage(db, journey_id) == "PROPOSED"
        rows = db.scalars(select(PaiPossibility).where(PaiPossibility.workspace_id == student.workspace_id,
                                                       PaiPossibility.source == "mirror")).all()
        assert rows, "the confirmed Mirror's lanes become paths"


@pytest.mark.asyncio
async def test_choose_moves_to_chosen_and_records_the_goal():
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        decision = choose(client, student, "electrical_engineering")
        assert stage(db, journey_id) == "CHOSEN"
        row = db.get(StudentJourney, journey_id)
        assert row.current_objective == decision["title"]
        assert row.active_goal == {"route_decision_id": decision["id"], "field_key": "electrical_engineering",
                                   "title": decision["title"], "route": decision["route"]}
        assert row.decisions[-1]["kind"] == "route_choice"
        assert row.decisions[-1]["route_decision_id"] == decision["id"]
        # Choosing another keeps CHOSEN and points the goal at the new route.
        second = choose(client, student, "computer_engineering")
        assert stage(db, journey_id) == "CHOSEN"
        assert db.get(StudentJourney, journey_id).active_goal["route_decision_id"] == second["id"]


@pytest.mark.asyncio
async def test_withdraw_returns_to_proposed_and_clears_the_goal():
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        decision = choose(client, student, "electrical_engineering")
        response = client.post("/v1/roadmap/withdraw", params={"network": student.workspace_id}, headers=TOKEN)
        assert response.status_code == 200, response.text
        assert stage(db, journey_id) == "PROPOSED"
        row = db.get(StudentJourney, journey_id)
        assert row.active_goal is None and row.current_objective is None
        assert row.decisions[-1] == {**row.decisions[-1], "kind": "route_withdrawn", "route_decision_id": decision["id"]}


@pytest.mark.asyncio
async def test_os_escalation_works_after_a_choice():
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        body = {"workspace_id": student.workspace_id, "journey_id": journey_id,
                "reason_type": "blocking_gap", "details": "Intake has closed"}
        with patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"):
            result = client.post("/v1/escalations", json=body, headers={"X-PAI-Service-Token": "local-test-token"})
        assert result.status_code == 200, result.text
        assert stage(db, journey_id) == "DIRECTION"


@pytest.mark.asyncio
async def test_chat_rethink_moves_to_direction_and_keeps_the_route():
    from app.pai_c.deep.actions import dispatch_action
    from app.pai_c.deep.context import DeepContext
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.deep.turn_input import CounselorTurnInput
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        decision = choose(client, student, "electrical_engineering")
        journey = JourneyService(db).get(student.workspace_id, journey_id)
        turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id, "Not sure any more",
                                  (), None, str(uuid4()), student.next_timestamp(), f"human:{student.user_id}", False)
        context = DeepContext("", {}, CounselorNotebookData(), journey, 0)
        assert await dispatch_action(db, turn, {"type": "rethink", "reason": "Unsure"}, context) == ("rethink", "accepted")
        assert stage(db, journey_id) == "DIRECTION"
        row = db.get(RouteDecision, decision["id"])
        assert row.withdrawn_at is None and row.field_key == "electrical_engineering"


@pytest.mark.asyncio
@pytest.mark.parametrize("stuck", [["ASSESSING"], ["ASSESSING", "NEEDS_INFO"]])
async def test_a_journey_stuck_in_old_research_stages_can_still_choose(stuck):
    async with confirmed_student() as (client, student, db, journey_id):
        # Journeys from before the engine were left waiting on roadmap research.
        db.get(StudentJourney, journey_id).current_stage = "RESEARCHING"
        db.commit()
        for name in stuck:
            JourneyService(db).set_counselor_stage(student.workspace_id, journey_id, name)
        db.commit()
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        assert stage(db, journey_id) == "CHOSEN"


@pytest.mark.asyncio
async def test_choose_before_the_mirror_leaves_the_stage_alone():
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        db.commit()
        with_routes(student, db)
        client = client_for(student)
        try:
            choose(client, student, "electrical_engineering")
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert stage(db, journey.id) == "IDENTITY"


async def confirm_mirror(client, student, db, version):
    response = client.post("/v1/counselor/summary/confirm", params={"network": student.workspace_id},
                           json={"version": version}, headers=TOKEN)
    assert response.status_code == 200, response.text
    db.expire_all()
    job = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_RESEARCH)
                     .order_by(BackgroundJob.created_at.desc())).first()
    assert (await confirmed_research_job(job, db))["status"] == "done"


def redraft_mirror(student, db, journey_id):
    """A new Mirror draft after a rethink, on the existing notebook."""
    from app.models import EventRecord
    from app.pai_c.deep.notebook import NotebookService
    from tests.test_counselor_mirror import mirror_data
    event_id = str(uuid4())
    db.add(EventRecord(id=event_id, network_id=student.workspace_id, type="workspace.message.posted",
                       source=f"human:{student.user_id}", target="channel/pai-counselor",
                       payload={"content": "Here is what changed."}, timestamp=student.next_timestamp()))
    db.commit()
    version = NotebookService(db).get(student.workspace_id).version
    result = JourneyService(db).set_counselor_summary(student.workspace_id, journey_id, mirror_data(),
                                                      "A new picture.", event_id, notebook_version=version,
                                                      channel="channel/pai-counselor")
    db.commit()
    return result


def assert_chosen_with_goal(db, journey_id, decision):
    assert stage(db, journey_id) == "CHOSEN"
    row = db.get(StudentJourney, journey_id)
    assert row.current_objective == decision["title"]
    assert row.active_goal["route_decision_id"] == decision["id"]


@pytest.mark.asyncio
async def test_choosing_again_records_the_replaced_route_as_withdrawn():
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        first = choose(client, student, "electrical_engineering")
        second = choose(client, student, "computer_engineering")
        db.expire_all()
        kinds = [(item["kind"], item["route_decision_id"]) for item in db.get(StudentJourney, journey_id).decisions]
        assert kinds[-3:] == [("route_choice", first["id"]), ("route_withdrawn", first["id"]),
                              ("route_choice", second["id"])]


@pytest.mark.asyncio
async def test_mirror_reconfirmed_after_rethink_returns_to_chosen():
    from app.pai_c.deep.actions import dispatch_action
    from app.pai_c.deep.context import DeepContext
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.deep.turn_input import CounselorTurnInput
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        decision = choose(client, student, "electrical_engineering")
        journey = JourneyService(db).get(student.workspace_id, journey_id)
        turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id, "Not sure any more",
                                  (), None, str(uuid4()), student.next_timestamp(), f"human:{student.user_id}", False)
        context = DeepContext("", {}, CounselorNotebookData(), journey, 0)
        assert await dispatch_action(db, turn, {"type": "rethink", "reason": "Unsure"}, context) == ("rethink", "accepted")
        assert stage(db, journey_id) == "DIRECTION"
        redraft = redraft_mirror(student, db, journey_id)
        await confirm_mirror(client, student, db, redraft.counselor_summary_draft["version"])
        assert_chosen_with_goal(db, journey_id, decision)


@pytest.mark.asyncio
async def test_route_chosen_before_the_mirror_is_chosen_once_it_is_confirmed():
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        db.commit()
        with_routes(student, db)
        client = client_for(student)
        try:
            decision = choose(client, student, "electrical_engineering")
            assert stage(db, journey.id) == "IDENTITY"
            draft_ready(student, db)
            await confirm_mirror(client, student, db, 1)
            assert_chosen_with_goal(db, journey.id, decision)
        finally:
            app.dependency_overrides.pop(get_db, None)
