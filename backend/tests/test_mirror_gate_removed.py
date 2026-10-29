"""The Mirror has no confirm gate (FOUR_FEATURES_SPEC 2.3-2.5).

Paths are explored as soon as they exist, research runs are keyed by the Vault
version, and the journey follows the Vault: DIRECTION -> MIRROR when the state
card is ready (set by the reconciler), MIRROR -> PROPOSED when the first paths
are saved (set by the Path engine job). Fake models only.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import BackgroundJob, ExecutionRun, StudentJourney, StudentJourneyEvent
from app.pai_c.mirror import MirrorEngine
from app.research.gateway import request_research
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import client_for, fake_post, prepare
from tests.test_mirror_engine import QUOTE, _education, _record
from tests.test_roadmap_engine import add_education, add_path, field_title, fsc

BACKEND = Path(__file__).resolve().parents[1]
HEADERS = {"X-Workspace-Token": "synthetic-test-only"}
DELEGATE = "app.research.gateway._delegate"


def stage(db, journey_id):
    db.expire_all()
    return db.get(StudentJourney, journey_id).current_stage


def accept_item(db, ws, item_type, value):
    candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type="vault_item", key=item_type,
        proposed_value=value, confidence=0.9, source_type="user_explicit",
        evidence={"quote": QUOTE}, allow_user_explicit=True)
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()


def queued(payload, run_id="run-1"):
    return {"ok": True, "data": {"run_id": run_id, "status": "pending"}}


def test_explore_works_without_mirror():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        journey = JourneyService(db).ensure_counselor(ws)
        db.commit()
        assert journey.current_stage == "IDENTITY" and not journey.counselor_summary_draft
        row = add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        client = client_for(student)
        try:
            with patch(DELEGATE, AsyncMock(side_effect=lambda payload, context: queued(payload))) as sent:
                response = client.post(f"/v1/counselor/paths/{row.id}/explore", params={"network": ws},
                                       headers=HEADERS)
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert response.status_code == 200, response.text
        constraints = sent.await_args.args[0]["constraints"]
        from app.pai_c.paths.currency import current_relevance
        assert constraints["relevance_version"] == current_relevance(db, ws)
        assert "mirror_version" not in constraints
        assert "mirror_version" not in constraints["capability_input"]["brief"]


@pytest.mark.asyncio
async def test_programs_run_keyed_by_relevance_version():
    """Fix round 1: runs are keyed by the path-relevant Vault
    (`relevance_version`), not the whole Vault version."""
    from app.pai_c.paths.currency import current_relevance
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        journey = JourneyService(db).ensure_counselor(ws)
        row = add_path(student, db, field_title("electrical_engineering"), "electrical_engineering",
                       status="exploring")
        version = current_relevance(db, ws)
        db.add(ExecutionRun(workspace_id=ws, requested_by="pai", task_type="path_explain", objective="Explain",
                            status="completed", constraints={"possibility_id": row.id, "relevance_version": version}))
        db.commit()
        kwargs = dict(db=db, journey=JourneyService(db).get(ws, journey.id),
                      tool_context=SimpleNamespace(workspace_id=ws), possibility_id=row.id)
        with patch(DELEGATE, AsyncMock(side_effect=lambda payload, context: queued(payload))) as sent:
            assert (await request_research("program_search", ws, **kwargs))["ok"]
        constraints = sent.await_args.args[0]["constraints"]
        assert constraints["relevance_version"] == version and "vault_version" not in constraints
        assert f":relevance:{version}" in constraints["research_key"]
        add_education(student, db, fsc("pre_engineering", 78))  # education is path-relevant
        assert current_relevance(db, ws) != version


REMOVED = re.compile(r"mirror_is_current|from_mirror|summary/confirm|summary/edit|summary/feedback|"
                     r"\bmirror_version\b|counselor\.mirror_research|queue_counselor_research|"
                     r"request_counselor_summary_changes|set_counselor_summary|CounselorMirrorFeedback|"
                     r"mirror_confirmed|summary_confirmed|mirror_allowed")


def test_no_route_or_job_references_mirror_confirmed():
    offenders = []
    for path in (BACKEND / "app").rglob("*"):
        if path.suffix not in {".py", ".json", ".md"} or "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if REMOVED.search(line):
                offenders.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/counselor/summary" in routes
    assert not {f"/v1/counselor/summary/{name}" for name in ("confirm", "edit", "feedback")} & routes
    from app.capabilities import get_capability_registry
    for job_type in ("counselor.mirror", "counselor.mirror_research"):
        assert get_capability_registry().get(job_type) is None
    for gone in ("app/pai_c/deep/mirror.py", "app/pai_c/deep/mirror_schema.py", "app/pai_c/deep/prompts/mirror.md",
                 "app/pai_c/summary_access.py", "app/pai_c/policy/actions/explore_correction.md"):
        assert not (BACKEND / gone).exists(), gone


def test_reconciler_moves_direction_to_mirror_when_ready():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, journey, _ = prepare(student, db)
        _education(db, ws)
        _record(db, ws, "goal", {"goal_type": "study", "title": "Electrical Engineering"})
        accept_item(db, ws, "interest", {"text": "Robotics"})
        assert not MirrorEngine(db).build(ws)["ready"]
        assert stage(db, journey.id) == "DIRECTION"
        accept_item(db, ws, "interest", {"text": "Circuits"})
        assert MirrorEngine(db).build(ws)["ready"]
        assert stage(db, journey.id) == "MIRROR"
        event = db.scalars(select(StudentJourneyEvent).where(
            StudentJourneyEvent.journey_id == journey.id, StudentJourneyEvent.event_type == "journey.stage_changed")
            .order_by(StudentJourneyEvent.created_at.desc())).first()
        assert event.payload == {"from": "DIRECTION", "to": "MIRROR"}
        # Later writes leave MIRROR alone; the Path engine moves it on.
        accept_item(db, ws, "interest", {"text": "Drawing"})
        assert stage(db, journey.id) == "MIRROR"


async def run_paths(student, db):
    from app.pai_c.paths.analyzer import enqueue_path_analysis, path_analysis_job
    from tests.test_path_analyzer import analysis, path
    job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="student")
    db.commit()
    reply = __import__("json").dumps(analysis(path("electrical_engineering")))
    with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value=reply)), \
         patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock(side_effect=fake_post(student))):
        return await path_analysis_job(db.get(BackgroundJob, job_id), db)


@pytest.mark.asyncio
async def test_first_paths_move_mirror_to_proposed():
    from tests.test_path_analyzer import add_education as add_fsc, seed
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = seed(student, db)
        add_fsc(student, db)
        assert JourneyService(db).mark_mirror_ready(student.workspace_id).current_stage == "MIRROR"
        db.commit()
        assert (await run_paths(student, db))["status"] == "stored"
        assert stage(db, journey.id) == "PROPOSED"
    # A Mirror that became ready while the stage lagged in DIRECTION goes through MIRROR.
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = seed(student, db)
        add_fsc(student, db)
        with patch.object(MirrorEngine, "ready", return_value=True):
            assert (await run_paths(student, db))["status"] == "stored"
        assert stage(db, journey.id) == "PROPOSED"
        moves = [row.payload for row in db.scalars(select(StudentJourneyEvent).where(
            StudentJourneyEvent.journey_id == journey.id, StudentJourneyEvent.event_type == "journey.stage_changed")
            .order_by(StudentJourneyEvent.created_at)).all()]
        assert moves[-2:] == [{"from": "DIRECTION", "to": "MIRROR"}, {"from": "MIRROR", "to": "PROPOSED"}]
    # Paths before the Mirror is ready leave the stage alone.
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = seed(student, db)
        add_fsc(student, db)
        with patch.object(MirrorEngine, "ready", return_value=False):
            assert (await run_paths(student, db))["status"] == "stored"
        assert stage(db, journey.id) == "DIRECTION"


def test_escalation_still_works_after_choose():
    from app.pai_c.paths.analyzer import propose_after_paths
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, journey, _ = prepare(student, db)
        JourneyService(db).mark_mirror_ready(ws)
        add_education(student, db, fsc("pre_engineering", 78))
        add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        propose_after_paths(db, ws, actor="system:paths")
        db.commit()
        assert stage(db, journey.id) == "PROPOSED"
        client = client_for(student)
        try:
            response = client.post("/v1/roadmap/choose", params={"network": ws}, headers=HEADERS,
                                   json={"field_key": "electrical_engineering"})
            assert response.status_code == 200, response.text
            assert stage(db, journey.id) == "CHOSEN"
            body = {"workspace_id": ws, "journey_id": journey.id, "reason_type": "blocking_gap",
                    "details": "Intake has closed"}
            with patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"):
                result = client.post("/v1/escalations", json=body,
                                     headers={"X-PAI-Service-Token": "local-test-token"})
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert result.status_code == 200, result.text
        assert stage(db, journey.id) == "DIRECTION"


@pytest.mark.asyncio
async def test_legacy_mirror_draft_ignored():
    from app.pai_c.deep.context import guided_state
    from app.pai_c.mirror.text_job import JOB_MIRROR_TEXT, mirror_text_job
    from app.pai_c.policy.controller import Decision
    from tests.test_mirror_text_job import GOOD, _reply
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, journey, snapshot = prepare(student, db)
        legacy = {"type": "mirror", "status": "awaiting_confirmation", "version": 2,
                  "mirror": {"intro": "An old picture."}, "channel": "channel/pai-counselor"}
        db.get(StudentJourney, journey.id).counselor_summary_draft = legacy
        db.commit()
        _education(db, ws)
        accept_item(db, ws, "interest", {"text": "Robotics"})
        card = MirrorEngine(db).build(ws)
        assert card["text"] is None  # the old picture is never shown as the Mirror text
        decision = Decision("explore", "explore_area", "history", True, False, False)
        state = guided_state(db, ws, decision, {}, [])
        assert state["stage"] == "getting_to_know"
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.workspace_id == ws,
                                                    BackgroundJob.job_type == JOB_MIRROR_TEXT))
        with patch("app.pai_c.mirror.text_job.chat_completion", AsyncMock(return_value=_reply(GOOD))):
            assert (await mirror_text_job(job, db))["status"] == "written"
        db.expire_all()
        draft = db.get(StudentJourney, journey.id).counselor_summary_draft
        assert draft["type"] == "mirror_state" and draft["text"] == " ".join(GOOD) and draft["version"] == 3
        assert "mirror" not in draft and "status" not in draft


def test_old_mirror_prompt_is_gone_and_documented_as_removed():
    from app.pai_c.deep.prompts import load_prompt
    with pytest.raises((KeyError, ValueError)):
        load_prompt("mirror")
    docs = BACKEND.parent / "docs/counselor/COUNSELOR_V3_PROMPTS.md"
    if not docs.exists():
        pytest.skip("docs are not mounted")
    text = docs.read_text(encoding="utf-8")
    assert "## 3. `mirror.md`" not in text and "## 3. (removed)" in text
    assert "explore_correction" not in text
