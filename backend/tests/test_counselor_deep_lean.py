"""Lean discovery boundaries; all model and Operator calls are fakes."""

import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import config
from app.counseling.deep.actions import dispatch_action
from app.counseling.deep.context import DeepContext, build_context
from app.counseling.deep.notebook import NotebookService, NotebookVersionConflict
from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.counseling.deep.sensitive import check_notebook_before_mirror
from app.counseling.deep.turn_input import CounselorTurnInput
from app.counseling.research_gateway import request_research
from app.journey import JourneyService
from app.models import CounselorNotedQuestion, EventRecord, ExecutionRun, Roadmap, StudentJourney
from scripts.counselor_eval_support import StudentSession
from scripts.eval_counselor_deep import run_evaluation


def source_turn(student, db):
    event_id = str(uuid4())
    timestamp = student.next_timestamp()
    db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                       type="workspace.message.posted", source=f"human:{student.user_id}",
                       target="channel/pai-counselor", payload={"content": "A factual question"},
                       timestamp=timestamp))
    db.commit()
    return CounselorTurnInput("channel/pai-counselor", student.workspace_id,
                              "A factual question", (), None, event_id, timestamp,
                              f"human:{student.user_id}", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [
    {"type": "note_question", "question_to_research": "A deferred question?"},
    {"type": "ask_research", "research_question": "A deferred question?"},
    {"type": "ask_research", "question": "A deferred question?"},
])
async def test_deferred_question_persists_once_without_operator(action):
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        context = DeepContext("", {}, CounselorNotebookData(), None, 0)
        executor = AsyncMock()
        with patch("app.tools.get_tool_executor", return_value=executor):
            assert await dispatch_action(db, turn, action, context) == ("note_question", "recorded")
            assert await dispatch_action(db, turn, action, context) == ("note_question", "duplicate")
        executor.execute.assert_not_awaited()
        rows = db.scalars(select(CounselorNotedQuestion)).all()
        assert len(rows) == 1
        assert (rows[0].workspace_id, rows[0].source_event_id, rows[0].status,
                rows[0].question_to_research) == (
                    student.workspace_id, turn.source_event_id, "open", "A deferred question?")
        assert await dispatch_action(db, turn, {"type": "none", "research_question": "Ignore?"}, context) == ("none", "none")
        NotebookService(db).delete_for_workspace(student.workspace_id)
        db.commit()
        assert db.scalar(select(CounselorNotedQuestion)) is None


@pytest.mark.asyncio
async def test_question_cannot_use_another_workspace_source_or_blank_question():
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        context = DeepContext("", {}, CounselorNotebookData(), None, 0)
        for invalid in (replace(turn, workspace_id=str(uuid4())),
                        replace(turn, source_event_id=str(uuid4()))):
            assert await dispatch_action(db, invalid, {"type": "note_question",
                "question_to_research": "A question?"}, context) == ("note_question", "ignored")
        assert await dispatch_action(db, turn, {"type": "note_question",
            "question_to_research": "  "}, context) == ("note_question", "ignored")
        assert db.scalar(select(CounselorNotedQuestion)) is None


def research_journey(student, db, stage="RESEARCHING", confirmed=False):
    journey = JourneyService(db).ensure_counselor(student.workspace_id)
    row = db.get(StudentJourney, journey.id)
    row.current_stage = stage
    row.counselor_summary_draft = {"status": "confirmed" if confirmed else "draft"}
    db.commit()
    return JourneyService(db).get(student.workspace_id, journey.id)


@pytest.mark.asyncio
async def test_deep_context_has_only_roadmaps_after_mirror_confirmation():
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        journey = research_journey(student, db, confirmed=False)
        db.add(Roadmap(workspace_id=student.workspace_id, journey_id=journey.id,
                       origin="stated_goal", title="Existing route", sources=[]))
        db.commit()
        assert "<research>" not in (await build_context(db, student.workspace_id, turn)).text
        research_journey(student, db, confirmed=True)
        text = (await build_context(db, student.workspace_id, turn)).text
        research = json.loads(text.split("<research>")[1].split("</research>")[0])
        assert set(research) == {"roadmaps"}
        assert research["roadmaps"][0]["title"] == "Existing route"


@pytest.mark.asyncio
async def test_research_gateway_enforces_deep_confirmation_and_keeps_legacy():
    with StudentSession() as student, student.factory() as db:
        journey = research_journey(student, db)
        ctx = SimpleNamespace(workspace_id=student.workspace_id)
        kwargs = dict(db=db, journey=journey, goals=[], understanding={}, tool_context=ctx)
        with patch("app.counseling.research_gateway._delegate_existing_research",
                   new=AsyncMock(return_value={"ok": True})) as delegate:
            with patch.object(config, "PAI_COUNSELOR_MODE", "deep"):
                assert await request_research("roadmap_light", student.workspace_id, **kwargs) is None
                delegate.assert_not_awaited()
                kwargs["journey"] = research_journey(student, db, confirmed=True)
                assert await request_research("roadmap_light", student.workspace_id, **kwargs) == {"ok": True}
            kwargs["journey"] = research_journey(student, db)
            with patch.object(config, "PAI_COUNSELOR_MODE", "legacy"):
                assert await request_research("roadmap_light", student.workspace_id, **kwargs) == {"ok": True}
            kwargs["tool_context"] = SimpleNamespace(workspace_id="another-workspace")
            assert await request_research("roadmap_light", student.workspace_id, **kwargs) is None
            with pytest.raises(ValueError, match="unknown"):
                await request_research("other", student.workspace_id, **kwargs)


@pytest.mark.asyncio
async def test_stale_refresh_routes_through_gateway_and_keeps_chosen_stage():
    from app.counseling.research_flow import delegate_research_if_ready
    with StudentSession() as student, student.factory() as db:
        journey = research_journey(student, db, "CHOSEN")
        db.add(Roadmap(workspace_id=student.workspace_id, journey_id=journey.id,
                       origin="stated_goal", title="Stale route", generation_status="stale"))
        db.commit()
        kwargs = dict(refresh_key="source-change")
        with patch("app.counseling.research_gateway._delegate_existing_research",
                   new=AsyncMock(return_value={"ok": True})) as delegate:
            result = await delegate_research_if_ready(
                db, student.workspace_id, journey, [], {},
                SimpleNamespace(workspace_id=student.workspace_id), **kwargs)
            assert result == {"ok": True}
            assert delegate.call_args.kwargs["refresh_key"] == "source-change"
        assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "CHOSEN"


@pytest.mark.asyncio
async def test_gateway_reuses_existing_operator_payload_and_deduplicates_runs():
    with StudentSession() as student, student.factory() as db:
        journey = research_journey(student, db, confirmed=True)
        ctx = SimpleNamespace(workspace_id=student.workspace_id)
        executor = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
        goals = [{"id": "goal", "title": "Student route", "details": {
            "underlying_objective": "An education goal", "constraints": []}}]
        with patch.object(config, "PAI_COUNSELOR_MODE", "deep"), \
                patch("app.tools.get_tool_executor", return_value=executor):
            assert await request_research("roadmap_light", student.workspace_id,
                db=db, journey=journey, goals=goals, understanding={}, tool_context=ctx) == {"ok": True}
            name, payload, used_ctx = executor.execute.call_args.args
            assert name == "operator.delegate" and used_ctx is ctx
            assert payload["task_type"] == "roadmap_research"
            assert payload["constraints"]["capability_input"]["brief"]["goal_id"] == "goal"
            db.add(ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                objective="Existing research", task_type="roadmap_research", status="running",
                constraints=payload["constraints"]))
            db.commit()
            assert await request_research("roadmap_light", student.workspace_id,
                db=db, journey=journey, goals=goals, understanding={}, tool_context=ctx) is None
        executor.execute.assert_awaited_once()


def test_only_research_gateway_directly_calls_operator_delegate():
    directory = Path(__file__).resolve().parents[1] / "app" / "counseling"
    found = []
    for path in directory.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "operator.delegate"):
                found.append(path.name)
    assert found == ["research_gateway.py"]


@pytest.mark.asyncio
async def test_pre_mirror_check_batches_old_unchanged_content_and_persists_removals():
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        NotebookService(db).apply(student.workspace_id, {
            "person": {"daily_life": "An ordinary day"}, "values": ["flagged", "retained"]
        }, turn.source_event_id, expected_version=0)
        checked = []

        async def checker(entries):
            assert not db.in_transaction()
            checked.append(entries)
            return {"values[0]"}

        snapshot, removals = await check_notebook_before_mirror(
            student.workspace_id, db=db, checker=checker)
        assert len(checked) == 1
        assert {entry["path"] for entry in checked[0]} == {"person.daily_life", "values[0]", "values[1]"}
        assert snapshot.notebook.values == ["retained"]
        assert snapshot.notebook.mirror_ready is False
        assert snapshot.version == 2 and len(removals) == 1
        assert NotebookService(db).get(student.workspace_id).notebook.values == ["retained"]


@pytest.mark.asyncio
async def test_pre_mirror_check_refuses_a_concurrent_notebook_change():
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        NotebookService(db).apply(student.workspace_id, {"values": ["old"]}, turn.source_event_id)

        async def checker(entries):
            with student.factory() as other:
                NotebookService(other).apply(student.workspace_id, {"values": ["new"]},
                                             turn.source_event_id, expected_version=1)
            return set()

        with pytest.raises(NotebookVersionConflict):
            await check_notebook_before_mirror(student.workspace_id, db=db, checker=checker)
        assert NotebookService(db).get(student.workspace_id).notebook.values == ["new"]


@pytest.mark.asyncio
async def test_recorded_harness_reports_note_question_without_research(tmp_path):
    from scripts.eval_counselor_deep import PERSONAS, load_personas
    persona = next(item for item in load_personas(PERSONAS) if item["id"] == "danish")
    persona["recorded_turns"][0]["counselor"]["action"] = {
        "type": "ask_research", "research_question": "A deferred question?"}
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "one.json").write_text(json.dumps(persona), encoding="utf-8")
    result = await run_evaluation(fixture_dir=fixtures, result_dir=tmp_path / "results")
    turn = result["personas"][0]["turns"][0]
    assert turn["action"]["type"] == "note_question"
    assert turn["action_status"] == "recorded"
    assert result["personas"][0]["metrics"]["note_question"] == 1
    assert {call["phase"] for call in turn["usage"]} == {"counselor", "analyst", "memory_extractor"}


@pytest.mark.asyncio
async def test_per_turn_extraction_fallback_does_not_skip_intervening_messages():
    from app.counseling import runtime
    from app.models import BackgroundJob

    with StudentSession() as student, student.factory() as db:
        sources = []
        with patch.object(config, "PAI_COUNSELOR_MODE", "deep"), \
                patch.object(config, "PAI_API_KEY", "fake"), \
                patch("app.counseling.deep.turn.chat_completion", new=AsyncMock(
                    return_value='{"reply":"What happened next?","action":{"type":"none"}}')):
            for _ in range(6):
                turn = source_turn(student, db)
                sources.append(turn.source_event_id)
                await runtime._run_turn(db, student.workspace_id, {
                    "id": turn.source_event_id, "source": turn.source,
                    "target": turn.channel, "payload": {"content": turn.student_text},
                    "timestamp": turn.timestamp, "metadata": {}}, 0)
        jobs = db.scalars(select(BackgroundJob).where(
            BackgroundJob.workspace_id == student.workspace_id,
            BackgroundJob.job_type == "memory.extract")).all()
        assert {job.payload["user_event_id"] for job in jobs} == set(sources)
        assert len(jobs) == 6


@pytest.mark.asyncio
async def test_legacy_model_tools_cannot_bypass_research_gateway():
    from app.counseling import runtime
    from app.counseling.policy import PolicyDecision

    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        response = AsyncMock(return_value="What matters most to you?")
        with patch.object(config, "PAI_API_KEY", "fake"), \
                patch.object(config, "PAI_MEMORY_CONTEXT_ENABLED", False), \
                patch("app.memory.profile_completion.ProfileCompletionService.evaluate", return_value={
                    "enforced": False, "foundationReady": True, "counselorMode": "open"}), \
                patch("app.counseling.turn_semantics.classify_turn", new=AsyncMock(return_value={})), \
                patch("app.counseling.policy.CounselingPolicy.decide", return_value=PolicyDecision(
                    "COUNSEL", None, True, True, True, 1)), \
                patch("app.counseling.core.CounselorCore.respond", response), \
                patch("app.counseling.reply_guard.guard_reply", new=AsyncMock(
                    return_value="What matters most to you?")):
            await runtime._run_legacy_turn(db, student.workspace_id, {
                "id": turn.source_event_id, "source": turn.source, "target": turn.channel,
                "payload": {"content": turn.student_text}, "timestamp": turn.timestamp}, 0)
        tool_context = response.call_args.kwargs["tool_context"]
        assert tool_context is not None
        assert "operator.delegate" not in tool_context.allowed_tools
