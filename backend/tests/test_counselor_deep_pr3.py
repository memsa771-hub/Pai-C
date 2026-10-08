"""Offline deep Counselor turn, channel parity, actions and grounding."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import config
from app.counseling import runtime
from app.counseling.deep.actions import dispatch_action
from app.counseling.deep.context import DeepContext, build_context
from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.counseling.deep.turn import run_deep_turn
from app.counseling.deep.turn_input import CounselorTurnInput
from app.models import EventRecord, User, Workspace
from scripts.counselor_eval_support import StudentSession


def _turn(student, text="I want to study AI", channel="channel/chat", voice=False):
    return CounselorTurnInput(
        channel, student.workspace_id, text, (), None, str(uuid4()),
        student.next_timestamp(), f"human:{student.user_id}", voice,
    )


def _answer(reply, action=None):
    return json.dumps({"reply": reply, "action": action or {"type": "none"}})


@pytest.mark.asyncio
async def test_normal_deep_turn_uses_one_json_model_call():
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=_answer("Tell me about your day?"))
        with patch("app.counseling.deep.turn.chat_completion", model), \
                patch.object(config, "PAI_API_KEY", "fake"):
            result = await run_deep_turn(db, _turn(student))
        assert result.reply == "Tell me about your day?"
        assert model.await_count == 1
        assert model.call_args.kwargs["response_format"] == {"type": "json_object"}
        assert model.call_args.kwargs["model"] == config.PAI_COUNSELOR_MODEL
        assert model.call_args.kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_invalid_json_falls_back_to_plain_text_without_action():
    with StudentSession() as student, student.factory() as db:
        with patch("app.counseling.deep.turn.chat_completion",
                   new=AsyncMock(return_value="Tell me what you did last week?")) as model:
            result = await run_deep_turn(db, _turn(student))
        assert result.reply == "Tell me what you did last week?"
        assert result.action["type"] == "none"
        assert model.await_count == 1


@pytest.mark.asyncio
async def test_fenced_json_parse_retry_never_displays_json():
    with StudentSession() as student, student.factory() as db:
        with patch("app.counseling.deep.turn.chat_completion",
                   new=AsyncMock(return_value='```json\n{"reply":"What did you make?","action":{"type":"none"}}\n```')) as model:
            result = await run_deep_turn(db, _turn(student))
        assert result.reply == "What did you make?"
        assert model.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("opener", ["Great,", "Zabardast,", "bohat acha,", "bahut acha,",
                                          "kya baat hai,", "shabash,", "wah,", "بہت اچھا،",
                                          "زبردست،", "شاباش،"])
async def test_praise_openers_removed_and_two_questions_trimmed(opener):
    with StudentSession() as student, student.factory() as db:
        text = f"{opener} Tell me what you built? How long did it take?"
        with patch("app.counseling.deep.turn.chat_completion", new=AsyncMock(return_value=_answer(text))):
            result = await run_deep_turn(db, _turn(student))
        assert result.reply == "Tell me what you built?"


@pytest.mark.asyncio
async def test_devanagari_retries_once_then_uses_fixed_fallback():
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(side_effect=[_answer("मुझे बताओ?"), _answer("फिर बताओ?")])
        with patch("app.counseling.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student))
        assert model.await_count == 2
        assert "Reply again in Roman Urdu with Urdu words, no Devanagari" in model.call_args.kwargs["system_prompt"]
        assert result.reply == "Main aap ki baat samajh raha hoon. Aap is baare mein thora aur bata sakte hain?"
        assert result.action["type"] == "none"


@pytest.mark.asyncio
async def test_mirror_request_ignored_until_notebook_ready():
    with StudentSession() as student, student.factory() as db:
        turn = _turn(student)
        context = DeepContext("", {}, CounselorNotebookData(), None, 0)
        kind, status = await dispatch_action(db, turn, {"type": "mirror"}, context)
        assert (kind, status) == ("mirror", "ignored")
        row = db.scalar(select(EventRecord).where(EventRecord.type == "counselor.action.mirror"))
        assert row.payload["reason"] == "not_ready"


@pytest.mark.asyncio
async def test_research_action_is_limited_to_five_per_workspace_day():
    with StudentSession() as student, student.factory() as db:
        context = DeepContext("", {}, CounselorNotebookData(), None, 0)
        executor = AsyncMock()
        executor.execute.return_value = {"ok": True, "data": {"run_id": "run"}}
        with patch("app.tools.get_tool_executor", return_value=executor):
            statuses = []
            for index in range(6):
                _, status = await dispatch_action(
                    db, _turn(student), {"type": "ask_research", "question": f"What is fee {index}?"}, context,
                )
                statuses.append(status)
        assert statuses == ["accepted"] * 5 + ["rate_limited"]
        assert executor.execute.await_count == 5


@pytest.mark.asyncio
async def test_research_reservation_commits_before_operator_uses_another_session():
    with StudentSession() as student, student.factory() as db:
        context = DeepContext("", {}, CounselorNotebookData(), None, 0)

        async def delegate(*args):
            with student.factory() as separate_db:
                statuses = separate_db.scalars(select(EventRecord).where(
                    EventRecord.type == "counselor.action.ask_research",
                )).all()
                assert [row.payload["status"] for row in statuses] == ["pending"]
            return {"ok": True, "data": {"run_id": "run"}}

        executor = AsyncMock()
        executor.execute.side_effect = delegate
        with patch("app.tools.get_tool_executor", return_value=executor):
            _, status = await dispatch_action(
                db, _turn(student), {"type": "ask_research", "question": "What is the fee?"},
                context,
            )
        assert status == "accepted"
        event = db.scalar(select(EventRecord).where(
            EventRecord.type == "counselor.action.ask_research",
        ))
        assert event.payload == {"status": "accepted", "run_id": "run"}


@pytest.mark.asyncio
async def test_identity_marked_never_ask_and_other_workspace_excluded():
    with StudentSession() as student, student.factory() as db:
        db.get(User, student.user_id).display_name = "Danish"
        other_user = User(email="another-student@example.test", display_name="Private Other")
        db.add(other_user)
        db.flush()
        db.add(Workspace(name="Other workspace", owner_user_id=other_user.id))
        db.commit()
        context = await build_context(db, student.workspace_id, _turn(student))
        assert '"identity_never_ask"' in context.text
        assert "Danish" in context.text
        assert "Private Other" not in context.text
        assert set(context.section_tokens) == {"today", "profile", "notebook", "memory", "research", "journey"}


@pytest.mark.asyncio
async def test_voice_and_chat_same_turn_have_identical_model_input_and_reply():
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=_answer("What did you enjoy doing?"))
        with patch("app.counseling.deep.turn.chat_completion", model):
            chat = await run_deep_turn(db, _turn(student, channel="channel/chat"))
            voice = await run_deep_turn(db, _turn(student, channel="channel/voice", voice=True))
        assert chat.reply == voice.reply
        assert model.await_args_list[0].kwargs["messages"] == model.await_args_list[1].kwargs["messages"]


@pytest.mark.asyncio
async def test_runtime_posts_and_enqueues_extraction_once():
    with StudentSession() as student, student.factory() as db:
        event_data = {"id": str(uuid4()), "source": f"human:{student.user_id}",
                      "target": "channel/chat", "payload": {"content": "I finished ICS"},
                      "timestamp": student.next_timestamp(), "metadata": {}}
        db.add(EventRecord(id=event_data["id"], network_id=student.workspace_id,
                           type="workspace.message.posted", source=event_data["source"],
                           target="channel/chat", payload=event_data["payload"],
                           timestamp=event_data["timestamp"]))
        db.commit()
        with patch.object(config, "PAI_COUNSELOR_MODE", "deep"), \
                patch.object(config, "PAI_API_KEY", "fake"), \
                patch("app.counseling.deep.turn.chat_completion",
                      new=AsyncMock(return_value=_answer("What are you doing now?"))) as model, \
                patch("app.memory.turn_hook.enqueue_turn_extraction") as enqueue:
            await runtime._run_turn(db, student.workspace_id, event_data, 0)
        assert student.transcript[-1]["content"] == "What are you doing now?"
        assert model.await_count == 1
        enqueue.assert_called_once()
