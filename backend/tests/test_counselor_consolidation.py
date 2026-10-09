"""Sole deep path and shared delivery regression tests; fake models only."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.pai_c import posting, runtime
from app.pai_c.deep.polish import is_counselor_fallback
from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.journey import JourneyService
from app.models import BackgroundJob, EducationRecord, EventRecord, MemoryCandidate, Roadmap
from scripts.counselor_eval_support import StudentSession


def test_one_runtime_and_no_deleted_imports_or_mode_switch():
    root = Path(__file__).resolve().parents[1] / "app"
    deleted = {"core", "turn_plan", "turn_semantics", "goal_transition", "evaluator",
               "continuous_discovery", "decision_sufficiency", "reply_guard", "turn_contract",
               "policy", "state", "research_flow"}
    assert not hasattr(config, "PAI_COUNSELOR_MODE")
    for retired in ("services/counselor_prompt.py", "memory/eval_behavior.py",
                    "memory/foundation_intake.py"):
        assert not (root / retired).exists()
    assert not hasattr(runtime, "_run_legacy_turn")
    for name in deleted:
        assert not (root / "pai_c" / f"{name}.py").exists()
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\bPAI_COUNSELOR_MODE\b", source)
        for name in deleted:
            assert f"app.pai_c.{name} import" not in source


@pytest.mark.parametrize("text,expected", [
    ("I couldn't finish that reply. Please retry your last message so I can pick up from here.", True),
    ("I can help with that. Let's work from what you've shared and take the next useful step.", True),
    ("A normal reply?", False),
])
def test_historical_voice_fallback_behavior_is_identical(text, expected):
    assert is_counselor_fallback(text) is expected


@pytest.mark.asyncio
async def test_selected_roadmap_uses_deep_prompt_and_is_workspace_scoped():
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        row = Roadmap(workspace_id=student.workspace_id, journey_id=journey.id,
                      origin="stated_goal", title="Selected route", route={"level": "degree"})
        db.add(row)
        db.commit()
        turn = CounselorTurnInput("channel/pai", student.workspace_id, "I opened this route.",
                                  (), None, "", None, f"human:{student.user_id}")
        with patch("app.pai_c.deep.turn.chat_completion", new=AsyncMock(
                return_value='{"reply":"Which part matters most?","action":{"type":"none"}}')) as model:
            result = await run_deep_turn(db, turn, roadmap_id=row.id, history=[])
            assert result.reply == "Which part matters most?"
            assert "<research>" in model.call_args.kwargs["system_prompt"]
            assert "Selected route" in model.call_args.kwargs["system_prompt"]
            assert model.await_count == 1
            with pytest.raises(ValueError, match="another workspace"):
                await run_deep_turn(db, turn, roadmap_id="other-workspace-roadmap", history=[])
            assert model.await_count == 1


@pytest.mark.asyncio
async def test_deep_output_cannot_write_profile_or_activate_goal():
    with StudentSession() as student:
        with patch.object(config, "PAI_API_KEY", "fake"), patch(
                "app.pai_c.deep.turn.chat_completion", new=AsyncMock(return_value=json.dumps({
                    "reply": "What did you enjoy about it?", "action": {"type": "none"},
                    "student_understanding_delta": {"education": [{"qualification_name": "Invented"}]},
                }))):
            await student.turn("I completed my qualification and want to study further.")
        with student.factory() as db:
            assert db.scalars(select(EducationRecord)).all() == []
            assert db.scalars(select(MemoryCandidate)).all() == []
            assert {job.job_type for job in db.scalars(select(BackgroundJob)).all()} == {
                "memory.extract", "counselor.analyze"}
            assert all(journey.active_goal is None for journey in
                       JourneyService(db).list_active(student.workspace_id))


@pytest.mark.asyncio
async def test_research_handoff_runs_through_the_deep_counselor_turn():
    from types import SimpleNamespace
    from app.pai_c import handoff as counselor_handoff
    from app.pai_c.deep.prompts import load_prompt
    session = Mock()
    deep_turn = AsyncMock(return_value=SimpleNamespace(reply="What matters most?"))
    history = [{"role": "user", "content": "earlier"}]
    with patch.object(counselor_handoff, "new_session", return_value=session), \
            patch.object(counselor_handoff, "run_deep_turn", deep_turn):
        reply = await counselor_handoff.explain_result("workspace", history, {"roadmap_research": True})
    assert reply == "What matters most?"
    deep_turn.assert_awaited_once()
    turn = deep_turn.await_args.args[1]
    assert turn.workspace_id == "workspace" and turn.source == "system:handoff"
    assert "roadmap_research" in turn.student_text
    assert deep_turn.await_args.kwargs == {"history": history, "instructions": "handoff"}
    session.close.assert_called_once()
    assert "BACKGROUND RESULT HANDOFF" in load_prompt("handoff")


@pytest.mark.asyncio
async def test_posting_runs_all_post_commit_hooks_before_return():
    # Capture the real function before StudentSession installs its test delivery.
    real_post = posting._post_response
    with StudentSession() as student, student.factory() as db:
        async def persist(event, context):
            db.add(EventRecord(
                id=event.id, network_id=event.network, type=event.type, source=event.source,
                target=event.target, payload=event.payload, metadata_=event.metadata,
                timestamp=event.timestamp))
        loop = Mock()
        with patch("app.eventing.factory.pipeline.process", new=AsyncMock(side_effect=persist)), \
                patch("app.infrastructure.cache.publish_event") as publish, \
                patch("app.pai_c.posting.asyncio.get_running_loop", return_value=loop):
            event_id = await real_post(db, student.workspace_id, "channel/pai", "pai",
                                       "What matters most?", 0, metadata={"voice_delegation_id": "voice-1"})
        assert db.get(EventRecord, event_id).metadata_["voice_delegation_id"] == "voice-1"
        publish.assert_called_once()
        assert loop.run_in_executor.call_count == 2
