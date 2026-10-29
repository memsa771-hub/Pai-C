"""Conversation/context/execution contracts, with real isolated storage."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import BackgroundJob, ExecutionRun, ProfileRequirement
from app.pai_c import runtime
from app.services import operator
from app.tools import ToolContext
from scripts.counselor_eval_support import StudentSession



@pytest.mark.asyncio
async def test_multi_turn_history_and_profile_jobs_survive_a_background_result():
    with StudentSession() as student:
        received = []

        async def model(**kwargs):
            received.append(kwargs)
            replies = ["I hear what matters to you about this route.", "Germany gives your plan a clear place to start.",
                       "That finding gives us a concrete next check."]
            return json.dumps({"reply": replies[len(received) - 1], "moves": ["reflect"], "action": {"type": "none"}})

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
            result = await asyncio.wait_for(operator.delegate(ctx, "Research programs", {"capability_input": {}}, None,
                                                             "study_abroad_matching", "path_explain"), 0.5)
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
async def test_result_is_interpreted_by_counselor_and_does_not_create_student_facts():
    with StudentSession() as student:
        with student.factory() as db:
            run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                objective="Find programs", status="completed",
                result={"final_message": "Detailed evidence and program constraints", "observations": []})
            db.add(run)
            db.commit()
            with patch.object(operator, "_result_stale", return_value=False), \
                 patch("app.pai_c.orchestrator.handle_research_result", AsyncMock(
                    return_value="Given your budget, verify the academic credits before paying an application fee.")) as explain:
                await operator._post_result(db, student.workspace_id, "channel/pai-counselor", run.id,
                                             "completed", "Found programs.")
            assert explain.call_args.args[2]["result"]["final_message"] == "Detailed evidence and program constraints"
            assert db.execute(select(BackgroundJob)).scalars().all() == []
            assert student.transcript[-1]["content"].startswith("Given your budget")
