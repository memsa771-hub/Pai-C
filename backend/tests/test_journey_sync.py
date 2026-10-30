"""The one stage sync and its re-plan guard (FOUR_FEATURES_SPEC 2.4).

Every journey here reaches its stage through real writes: Vault rows through
the reconciler (whose Mirror hook syncs the stage), notebook rows through the
analyst's stage step, paths through the Path engine job, a choice through the
roadmap API. A rethink or a PAI OS escalation is a re-plan: the student's next
fact must not undo it; only their own act (choosing, or asking for paths and
getting them) ends it. Fake models only.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import BackgroundJob, StudentJourney, VaultItem
from app.pai_c.mirror import MirrorEngine
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import client_for, fake_post, prepare
from tests.test_mirror_engine import _education, _record
from tests.test_mirror_gate_removed import accept_item, stage
from tests.test_roadmap_engine import add_education, add_path, field_title, fsc

HEADERS = {"X-Workspace-Token": "synthetic-test-only"}
CHANNEL = "channel/pai-counselor"


def make_ready(db, ws):
    """Education, a goal and two interests: the Mirror card is ready."""
    _education(db, ws)
    _record(db, ws, "goal", {"goal_type": "study", "title": "Electrical Engineering"})
    accept_item(db, ws, "interest", {"text": "Robotics"})
    accept_item(db, ws, "interest", {"text": "Circuits"})
    assert MirrorEngine(db).ready(ws)


def proposed_student(student, db):
    """The reviewer's probe setup: a ready Mirror, then a path, then one more
    fact. Each move is made by the reconciler's Mirror hook."""
    ws = student.workspace_id
    _, journey, _ = prepare(student, db)
    make_ready(db, ws)
    assert stage(db, journey.id) == "MIRROR"
    # Still the current education: an onboarded student always has a status (city, current level).
    add_education(student, db, fsc("pre_engineering", 78, academic_status="current"))
    add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
    accept_item(db, ws, "interest", {"text": "Drawing"})
    assert stage(db, journey.id) == "PROPOSED"
    return journey


async def rethink(db, student, journey_id):
    from app.pai_c.deep.actions import dispatch_action
    from app.pai_c.deep.context import DeepContext
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.deep.turn_input import CounselorTurnInput
    journey = JourneyService(db).get(student.workspace_id, journey_id)
    turn = CounselorTurnInput(CHANNEL, student.workspace_id, "Not sure any more", (), None, str(uuid4()),
                              student.next_timestamp(), f"human:{student.user_id}", False)
    context = DeepContext("", {}, CounselorNotebookData(), journey, 0)
    assert await dispatch_action(db, turn, {"type": "rethink", "reason": "Unsure"}, context) == ("rethink", "accepted")
    db.commit()
    assert stage(db, journey_id) == "DIRECTION"


def escalate(student, journey_id):
    client = client_for(student)
    body = {"workspace_id": student.workspace_id, "journey_id": journey_id, "reason_type": "blocking_gap",
            "details": "Intake has closed"}
    try:
        with patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"):
            result = client.post("/v1/escalations", json=body, headers={"X-PAI-Service-Token": "local-test-token"})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert result.status_code == 200, result.text


async def replan(kind, db, student, journey_id):
    if kind == "rethink":
        await rethink(db, student, journey_id)
    else:
        escalate(student, journey_id)
    assert stage(db, journey_id) == "DIRECTION"


def choose(student, field_key):
    client = client_for(student)
    try:
        response = client.post("/v1/roadmap/choose", params={"network": student.workspace_id}, headers=HEADERS,
                               json={"field_key": field_key})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def run_paths(student, db, *, reason, channel=None):
    """One Path engine run through the real job, with a fake model."""
    from app.pai_c.paths.analyzer import enqueue_path_analysis, path_analysis_job
    from tests.test_path_analyzer import analysis, path
    job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=channel, reason=reason)
    db.commit()
    reply = json.dumps(analysis(path("electrical_engineering")))
    job = db.get(BackgroundJob, job_id)
    with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value=reply)), \
         patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock(side_effect=fake_post(student))):
        result = await path_analysis_job(job, db)
    job = db.get(BackgroundJob, job_id)
    job.status, job.result = "succeeded", result
    db.commit()
    return result


def seed_for_paths(student, db):
    """The analyzer's evidence (tests.test_path_analyzer.seed) on a ready Mirror."""
    from tests.test_path_analyzer import add_education as add_fsc, seed
    _, journey, _ = seed(student, db)
    add_fsc(student, db)
    make_ready(db, student.workspace_id)
    assert stage(db, journey.id) == "MIRROR"
    return journey


# ---- the probe: one fact after a re-plan ------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rethink", "escalation"])
async def test_one_fact_after_a_replan_stays_in_direction(kind):
    with StudentSession() as student, student.factory() as db:
        journey = proposed_student(student, db)
        await replan(kind, db, student, journey.id)
        accept_item(db, student.workspace_id, "interest", {"text": "Music"})
        assert MirrorEngine(db).ready(student.workspace_id)
        assert stage(db, journey.id) == "DIRECTION"
        assert db.get(StudentJourney, journey.id).replan_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rethink", "escalation"])
async def test_choosing_after_a_replan_ends_it(kind):
    with StudentSession() as student, student.factory() as db:
        journey = proposed_student(student, db)
        first = choose(student, "electrical_engineering")
        assert stage(db, journey.id) == "CHOSEN"
        await replan(kind, db, student, journey.id)
        accept_item(db, student.workspace_id, "interest", {"text": "Music"})
        assert stage(db, journey.id) == "DIRECTION"  # the kept route does not pull it back
        decision = choose(student, "electrical_engineering")
        assert decision["id"] != first["id"]
        assert stage(db, journey.id) == "CHOSEN"
        row = db.get(StudentJourney, journey.id)
        assert row.replan_at is None and row.active_goal["route_decision_id"] == decision["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rethink", "escalation"])
async def test_an_asked_run_that_saves_paths_ends_a_replan(kind):
    with StudentSession() as student, student.factory() as db:
        journey = seed_for_paths(student, db)
        assert (await run_paths(student, db, reason="vault"))["status"] == "stored"
        assert stage(db, journey.id) == "PROPOSED"
        await replan(kind, db, student, journey.id)
        # A new fact queues a quiet (Vault) run; it saves paths but is not the student's ask.
        accept_item(db, student.workspace_id, "interest", {"text": "Music"})
        assert (await run_paths(student, db, reason="vault"))["status"] == "stored"
        assert stage(db, journey.id) == "DIRECTION"
        accept_item(db, student.workspace_id, "interest", {"text": "Chess"})
        assert (await run_paths(student, db, reason="asked", channel=CHANNEL))["status"] == "posted"
        assert stage(db, journey.id) == "PROPOSED"
        assert db.get(StudentJourney, journey.id).replan_at is None


# ---- readiness from either writer --------------------------------------------------

def test_a_notebook_write_that_makes_the_card_ready_advances_on_the_analyst_turn():
    from app.pai_c.deep.analysis import _advance_stage
    from app.pai_c.deep.notebook import NotebookService
    from tests.truth_map_fixtures import item
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        turn, journey, snapshot = prepare(student, db)
        _education(db, ws)
        _record(db, ws, "goal", {"goal_type": "study", "title": "Electrical Engineering"})
        assert not MirrorEngine(db).ready(ws) and stage(db, journey.id) == "DIRECTION"
        data = snapshot.notebook.model_dump(mode="json")
        data["self"] = [item(text, key=f"interest.{key}", id=key, evidence=text)
                        for key, text in (("robots", "I like building robots"), ("circuits", "I wire circuits"))]
        snapshot, _ = NotebookService(db).apply(ws, data, turn.source_event_id,
                                               expected_version=snapshot.version)
        db.commit()
        assert MirrorEngine(db).ready(ws)
        assert db.scalar(select(VaultItem.id).where(VaultItem.workspace_id == ws,
                                                    VaultItem.item_type == "interest")) is None
        _advance_stage(db, ws, snapshot.notebook)
        assert stage(db, journey.id) == "MIRROR"


def test_a_card_ready_before_direction_moves_on_when_the_analyst_reaches_direction():
    from app.pai_c.deep.analysis import _advance_stage
    from app.pai_c.memory import MemoryService
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        service = JourneyService(db)
        journey = service.ensure_counselor(ws)
        service.set_counselor_stage(ws, journey.id, "FOUNDATION")
        db.commit()
        make_ready(db, ws)
        add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        assert stage(db, journey.id) == "FOUNDATION"  # the hook moves nothing before DIRECTION
        with patch.object(MemoryService, "foundation_ready", return_value=True):
            _advance_stage(db, ws, MemoryService(db).truth_map(ws).notebook)
        assert stage(db, journey.id) == "PROPOSED"


@pytest.mark.asyncio
async def test_a_fresh_student_reaches_proposed_end_to_end():
    with StudentSession() as student, student.factory() as db:
        journey = seed_for_paths(student, db)
        assert db.get(StudentJourney, journey.id).mirror_ready_at is not None
        assert (await run_paths(student, db, reason="vault"))["status"] == "stored"
        assert stage(db, journey.id) == "PROPOSED"


# ---- hooks never undo a Vault write -----------------------------------------------

@pytest.mark.parametrize("loader", ["app.pai_c.mirror.text_job.mirror_types",
                                    "app.pai_c.paths.currency.trigger_types"])
def test_bad_policy_data_in_a_hook_keeps_the_vault_write(loader):
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        with patch(loader, side_effect=ValueError("bad policy")):
            accept_item(db, ws, "interest", {"text": "Robotics"})
        db.expire_all()
        assert db.scalar(select(VaultItem.id).where(VaultItem.workspace_id == ws,
                                                    VaultItem.item_type == "interest"))
