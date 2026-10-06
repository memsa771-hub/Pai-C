"""The same server tool boundary applies to text and transcribed voice."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.config import config
from app.counseling import runtime
from app.models import EventRecord, ExecutionRun
from app.memory.student_records import StudentRecordService
from app.services import operator
from scripts.counselor_eval_support import StudentSession


OPEN = {"enforced": False, "foundationReady": True, "counselorMode": "normal",
        "fields": [], "nextRequirement": None}
COLLECTING = {"enforced": True, "foundationReady": False,
              "counselorMode": "collection", "fields": [{
                  "key": "education.history", "tier": "critical", "status": "missing"}],
              "nextRequirement": {"key": "education.history",
                                  "question": "What are you studying now?"}}


def _delegate_call():
    return {"id": "call-1", "type": "function", "function": {
        "name": "operator__delegate", "arguments": json.dumps({
            "objective": "Research matching study routes", "task_type": "roadmap_research",
            "context_refs": ["vault", "memory"],
        })}}


async def _exercise(completion, *, voice=False):
    with StudentSession() as student:
        if completion is OPEN:
            with student.factory() as db:
                StudentRecordService(db).apply(
                    student.workspace_id, "goal",
                    {"goal_type": "education", "title": "Study abroad"},
                    source_type="user_explicit", claim_origin="student",
                    capture_method="conversation")
                db.commit()
        requests = []

        async def model(**kwargs):
            requests.append(kwargs)
            if kwargs.get("tools") and len(requests) == 1:
                return {"role": "assistant", "content": "", "tool_calls": [_delegate_call()]}
            return {"role": "assistant", "content": "I am checking the routes for you."}

        with patch.object(runtime, "chat_completion_tools", model), \
             patch.object(config, "PAI_API_KEY", "test"), \
             patch.object(config, "PAI_MEMORY_CONTEXT_ENABLED", False), \
             patch("app.memory.profile_completion.ProfileCompletionService.evaluate",
                   return_value=completion), \
             patch("app.counseling.goal_transition.resolve_or_activate_goal",
                   new=AsyncMock(return_value=None)), \
             patch("app.counseling.goal_transition.reviewed_route",
                   new=AsyncMock(return_value=False)), \
             patch("app.counseling.turn_semantics.classify_turn",
                   new=AsyncMock(return_value={"requested_work": True})), \
             patch("app.counseling.reply_guard.guard_reply",
                   new=AsyncMock(side_effect=lambda reply, **kwargs: reply)), \
             patch("app.memory.foundation_intake.capture_foundation_turn",
                   new=AsyncMock(return_value=False)), \
             patch("app.counseling.reply_guard.guard_collection_reply",
                   new=AsyncMock(side_effect=lambda reply, **kwargs: reply)), \
             patch.object(operator, "is_available", return_value=True), \
             patch.object(operator, "_execute", new=AsyncMock()):
            await student.turn("Please research routes for me.",
                               metadata={"voice_delegation_id": "voice-turn"} if voice else None)
            await asyncio.gather(*list(operator._running_tasks))

        with student.factory() as db:
            runs = db.execute(select(ExecutionRun)).scalars().all()
            audits = db.execute(select(EventRecord).where(
                EventRecord.type == "counselor.tool.result")).scalars().all()
            if completion is OPEN:
                assert len(runs) == 1
                assert runs[0].task_type == "roadmap_research"
                assert len(audits) == 1 and audits[0].visibility == "private"
                assert audits[0].payload["result"]["data"]["run_id"] == runs[0].id
                assert "operator__delegate" in {tool["function"]["name"]
                                                 for tool in requests[0]["tools"]}
                assert requests[1]["messages"][-1]["role"] == "tool"
                if voice:
                    reply = db.execute(select(EventRecord).where(
                        EventRecord.type == "workspace.message.posted",
                        EventRecord.source == "openagents:pai").order_by(
                            EventRecord.timestamp.desc())).scalars().first()
                    assert reply.metadata_["voice_delegation_id"] == "voice-turn"
            else:
                assert runs == [] and audits == []
                assert all(not request.get("tools") for request in requests)


def test_open_chat_delegates_and_persists_tool_result():
    asyncio.run(_exercise(OPEN))


def test_collecting_chat_has_no_execution_tools():
    asyncio.run(_exercise(COLLECTING))


def test_open_voice_turn_uses_the_same_delegation_path():
    asyncio.run(_exercise(OPEN, voice=True))
