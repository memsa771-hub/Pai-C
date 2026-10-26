"""Guard: the chat-linked roadmap system stays removed (ROADMAP_ENGINE_SPEC.md §4).

Routes come only from the deterministic engine and the Roadmap page; nothing in
chat, the reconciler or the old /v1/roadmaps API may build or change one.
"""

import ast
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from scripts.counselor_eval_support import StudentSession

BACKEND = Path(__file__).resolve().parents[1]
TOKEN = {"X-Workspace-Token": "synthetic-test-only"}
REMOVED_MODULES = ("app.pai_c.roadmaps", "app.plugins.roadmap_builder", "app.pai_c.deep.roadmaps",
                   "app.research.light", "app.routers.roadmaps")


@pytest.fixture
def client_for_student():
    with StudentSession() as student:
        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            yield TestClient(app), student, {"network": student.workspace_id}
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_old_roadmaps_api_is_gone(client_for_student):
    client, _, params = client_for_student
    for method, path in (("get", "/v1/roadmaps"), ("get", f"/v1/roadmaps/{uuid4()}"),
                         ("post", "/v1/roadmaps/custom"), ("post", f"/v1/roadmaps/{uuid4()}/choose")):
        assert getattr(client, method)(path, params=params, headers=TOKEN).status_code == 404, path


def test_prepare_path_roadmap_route_is_gone(client_for_student):
    client, _, params = client_for_student
    response = client.post(f"/v1/counselor/paths/{uuid4()}/roadmap", params=params, headers=TOKEN,
                           json={"explore_places": True})
    assert response.status_code == 404
    assert not any(getattr(route, "path", "").endswith("/{path_id}/roadmap") for route in app.routes)


def test_removed_modules_are_not_importable_or_imported():
    for name in REMOVED_MODULES:
        assert importlib.util.find_spec(name) is None, name
    banned = ("pai_c.roadmaps", "plugins.roadmap_builder", "pai_c.deep.roadmaps", "research.light")
    offenders = []
    for folder in (BACKEND / "app", BACKEND / "scripts"):
        for path in folder.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else
                         [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                if any(part in name for name in names for part in banned):
                    offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []


def test_mark_stale_job_is_not_registered():
    from app.capabilities import get_capability_registry
    registry = get_capability_registry()
    for capability in ("roadmaps.mark_stale", "research.refresh_stale", "roadmap.build"):
        assert registry.get(capability) is None, capability
    assert registry.owner_for_task_type("roadmap_research") is None


def test_reconciler_accepts_fact_without_roadmap_invalidation():
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    from app.models import BackgroundJob
    with StudentSession() as student, student.factory() as db:
        candidate = MemoryCandidateService(db).propose(
            student.workspace_id, "student_record", key="education",
            proposed_value={"qualification_name": "Completed qualification"},
            confidence=0.95, source_type="conversation", evidence={"quote": "My student statement"})
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.flush()
        job_types = set(db.scalars(select(BackgroundJob.job_type)).all())
    assert "roadmaps.mark_stale" not in job_types
    assert "memory.resume_research" in job_types  # accepted evidence still resumes paused runs


@pytest.mark.asyncio
async def test_chat_turn_context_has_no_roadmap_block():
    from app.journey import JourneyService
    from app.models import EventRecord, StudentJourney
    from app.pai_c.deep.context import build_context
    from app.pai_c.deep.turn_input import CounselorTurnInput
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        row = db.get(StudentJourney, journey.id)
        row.current_stage = "RESEARCHING"
        row.counselor_summary_draft = {"type": "mirror", "version": 1, "mirror": {}, "status": "confirmed"}
        event_id, timestamp = str(uuid4()), student.next_timestamp()
        db.add(EventRecord(id=event_id, network_id=student.workspace_id, type="workspace.message.posted",
                           source=f"human:{student.user_id}", target="channel/pai-counselor",
                           payload={"content": "Which route should I take?"}, timestamp=timestamp))
        db.commit()
        turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id, "Which route should I take?",
                                  (), None, event_id, timestamp, f"human:{student.user_id}", False)
        text = (await build_context(db, student.workspace_id, turn)).text
    assert "<compare>" not in text and "selected_roadmap" not in text and '"roadmaps"' not in text


def test_research_gateway_has_no_roadmap_kinds():
    import asyncio
    from app.research.gateway import request_research
    for kind in ("roadmap_light", "roadmap_deep", "stale_refresh"):
        with pytest.raises(ValueError, match="unknown Counselor research kind"):
            asyncio.run(request_research(kind, "workspace", db=_NoLockDb(), journey=None, tool_context=None))


class _NoLockDb:
    """Enough of a session for the gateway's dialect check (not PostgreSQL, so no lock)."""

    def get_bind(self):
        return type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()})()


@pytest.mark.asyncio
async def test_chat_rethink_moves_the_stage_but_never_the_chosen_route():
    from app.journey import JourneyService
    from app.models import RouteDecision, StudentJourney
    from app.pai_c.deep.actions import dispatch_action
    from app.pai_c.deep.context import DeepContext
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.deep.turn_input import CounselorTurnInput
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        db.get(StudentJourney, journey.id).current_stage = "CHOSEN"
        decision = RouteDecision(workspace_id=student.workspace_id, field_key="computer_science",
                                 title="Computer Science", verdict={}, route={}, steps=[], steps_done=[])
        db.add(decision)
        db.commit()
        journey = JourneyService(db).get(student.workspace_id, journey.id)
        turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id, "Not sure any more",
                                  (), None, str(uuid4()), student.next_timestamp(), f"human:{student.user_id}", False)
        context = DeepContext("", {}, CounselorNotebookData(), journey, 0)
        assert await dispatch_action(db, turn, {"type": "rethink", "reason": "Unsure"}, context) == ("rethink", "accepted")
        db.expire_all()
        assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "DIRECTION"
        assert db.get(RouteDecision, decision.id).withdrawn_at is None
