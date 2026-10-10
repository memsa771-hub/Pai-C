"""Conversation/context/execution contracts, with real isolated storage."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.memory.context import StudentContext
from app.memory.foreground import ForegroundContext, build_foreground_context
from app.models import BackgroundJob, ExecutionRun, ProfileRequirement
from app.pai_c import runtime
from app.services import operator, pai
from app.tools import ToolContext
from scripts.counselor_eval_support import StudentSession



@pytest.mark.asyncio
async def test_multi_turn_history_and_profile_jobs_survive_a_background_result():
    with StudentSession() as student:
        received = []

        async def model(**kwargs):
            received.append(kwargs)
            return json.dumps({"reply": "What matters most about this route?", "action": {"type": "none"}})

        with patch("app.pai_c.deep.turn.chat_completion", model), \
                patch.object(config, "PAI_API_KEY", "test"), \
                patch.object(config, "PAI_MEMORY_CONTEXT_ENABLED", False):
            await student.turn("I want to study abroad for a master's.")
            await student.turn("Germany.")
            with student.factory() as db:
                await student.post_response(db, student.workspace_id, "channel/pai-counselor", "pai",
                    "The source confirms a CS prerequisite; your transcript is the next check.", 0,
                    message_type="operator_result")
            await student.turn("What should I do with that finding?")

        assert len(received) == 3
        last_messages = received[-1]["messages"]
        assert sum(m["content"] == "What should I do with that finding?" for m in last_messages) == 1
        assert any("CS prerequisite" in m["content"] and m["role"] == "assistant" for m in last_messages)
        assert any("Germany" in m["content"] for m in last_messages)
        with student.factory() as db:
            jobs = db.execute(select(BackgroundJob)).scalars().all()
            assert len(jobs) == 6
            assert all(job.status == "pending" for job in jobs)  # never waited on extraction


@pytest.mark.asyncio
async def test_delegation_returns_while_execution_is_still_waiting():
    with StudentSession() as student:
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow(*args):
            started.set()
            await release.wait()

        ctx = ToolContext(student.workspace_id, "pai", None, conversation="pai-counselor")
        with patch.object(operator, "_execute", slow), patch.object(operator, "is_available", return_value=True):
            result = await asyncio.wait_for(operator.delegate(ctx, "Research programs", {}, None,
                                                             "study_abroad_matching"), 0.5)
            assert not started.is_set()
            assert result["ok"] and not release.is_set()
            with student.factory() as db:
                run = db.get(ExecutionRun, result["data"]["run_id"])
                assert run.context_refs == ["vault", "memory", "episodes"]
                assert run.constraints["student_intent"] == "study_abroad_matching"
            release.set()
            with student.factory() as db:
                job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "operator.run"))
                assert job.payload["run_id"] == result["data"]["run_id"]


@pytest.mark.asyncio
async def test_slow_vector_retrieval_keeps_time_for_canonical_fallback():
    async def slow(*args):
        await asyncio.sleep(10)

    canonical = StudentContext("w", vault={"preferences.target_countries": ["Germany"]})
    async def fallback(*args):
        return canonical

    with patch("app.memory.foreground._hybrid", slow), \
            patch("app.memory.foreground.run_bounded", fallback), \
            patch.object(config, "PAI_MEMORY_CONTEXT_TIMEOUT_MS", 700):
        started = time.monotonic()
        result = await build_foreground_context("w", "study abroad")
    assert result.mode == "lexical_fallback"
    assert "Germany" in result.block
    assert time.monotonic() - started < 0.9



@pytest.mark.asyncio
@pytest.mark.parametrize("verification,expected", [
    ('{"status":"completed","summary":"Found programs","completed_step_ids":["research"]}', "completed"),
    ("not valid JSON", "failed"),
])
async def test_operator_keeps_context_and_verifies_evidence_before_counselor_handoff(verification, expected):
    with StudentSession() as student:
        with student.factory() as db:
            run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                               objective="Find AI MSc programs", constraints={}, context_refs=["vault"])
            db.add(run)
            db.commit()
            run_id = run.id
        phases = AsyncMock(side_effect=["Use the budget to assess fit.",
                                         '[{"id":"research","title":"Read official programs"}]', verification])
        execution = AsyncMock(side_effect=[
            {"role": "assistant", "tool_calls": [{"id": "call1", "type": "function", "function": {
                "name": "web__fetch", "arguments": '{"url":"https://university.example/ai"}'}}]},
            {"role": "assistant", "content": "Program X requires CS credits: https://university.example/ai"},
        ])
        executor = SimpleNamespace(execute=AsyncMock(return_value={"ok": True, "data": {
            "url": "https://university.example/ai", "content": "CS credits required; fees EUR 0."}}))
        with patch.object(operator, "chat_completion", phases), \
                patch.object(operator, "chat_completion_tools", execution), \
                patch.object(operator, "_resolve_memory_context", return_value="Known budget EUR 12000 per year"), \
                patch.object(pai, "workspace_state_summary", AsyncMock(return_value="workspace")), \
                patch("app.tools.get_tool_executor", return_value=executor), \
                patch.object(operator, "_publish_run_updated"), \
                patch.object(operator, "_post_result", AsyncMock()) as handoff:
            await operator._execute(run_id, student.workspace_id, None, "Find AI MSc programs",
                                    {"no_submission": True}, ["vault"], "channel/pai-counselor")
        assert "EUR 12000" in execution.call_args_list[0].kwargs["system_prompt"]
        assert "no_submission" in execution.call_args_list[0].kwargs["messages"][0]["content"]
        assert "CS credits required" in phases.call_args_list[-1].kwargs["messages"][0]["content"]
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            assert run.status == expected
            assert run.result["observations"][0]["url"] == "https://university.example/ai"
        handoff.assert_awaited_once()


@pytest.mark.asyncio
async def test_result_is_interpreted_by_counselor_and_does_not_create_student_facts():
    with StudentSession() as student:
        with student.factory() as db:
            run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                objective="Find programs", status="completed",
                result={"final_message": "Detailed evidence and program constraints", "observations": []})
            db.add(run)
            db.commit()
            with patch.object(operator, "_baseline_is_current", return_value=True), \
                 patch("app.pai_c.orchestrator.handle_research_result", AsyncMock(
                    return_value="Given your budget, verify the academic credits before paying an application fee.")) as explain:
                await operator._post_result(db, student.workspace_id, "channel/pai-counselor", run.id,
                                             "completed", "Found programs.")
            assert explain.call_args.args[2]["result"]["final_message"] == "Detailed evidence and program constraints"
            assert db.execute(select(BackgroundJob)).scalars().all() == []
            assert student.transcript[-1]["content"].startswith("Given your budget")



@pytest.mark.asyncio
async def test_operator_result_cannot_bypass_unconfirmed_baseline():
    with StudentSession() as student:
        with student.factory() as db:
            db.add(ProfileRequirement(
                key="education.history", tier="critical", source_type="record_presence",
                source_key="education", selector="any",
                question="What is your current or highest qualification?",
                priority=100, version=1, enabled=True,
            ))
            run = ExecutionRun(
                workspace_id=student.workspace_id, requested_by="openagents:pai",
                objective="Rank universities for this student", status="completed",
                result={"final_message": "Secret personalized ranking", "observations": []},
            )
            db.add(run)
            db.commit()
            with patch.object(config, "PAI_PROFILE_COMPLETION_ROLLOUT_MODE", "all"), \
                    patch("app.pai_c.orchestrator.handle_research_result", AsyncMock()) as explain:
                await operator._post_result(
                    db, student.workspace_id, "channel/pai-counselor", run.id,
                    "completed", "Secret personalized ranking",
                )
        explain.assert_not_awaited()
        assert "Secret personalized ranking" not in student.transcript[-1]["content"]
        assert "confirm that my understanding" in student.transcript[-1]["content"]
