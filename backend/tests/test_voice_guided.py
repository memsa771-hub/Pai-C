"""Guided Voice: universal prompt, state block and reply repetition guard (offline)."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import CounselorNotedQuestion
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.policy.classifier import fallback_signals
from app.pai_c.policy.controller import Decision
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn

COUNSEL = Decision("counsel", "counsel", None, True, False, False)
REST = Decision("rest", "counsel", None, False, False, False)


def output(reply, action=None):
    return json.dumps({"reply": reply, "moves": ["reflect"], "action": action or {"type": "none"}})


def section(prompt, name):
    return json.loads(prompt.rsplit("<context>", 1)[1].split(f"<{name}>", 1)[1].split(f"</{name}>", 1)[0])


def test_guided_prompt_keeps_shared_sections_from_voice():
    guided, strict = load_prompt("voice_guided"), load_prompt("voice")
    assert guided.startswith("You are PAI, a counselor who stays with one student over a long time.")
    assert "THE COUNSELING LOOP" in guided and "often the best reply has no question." in guided
    shared = strict[strict.index("WHAT YOU ANSWER AND WHAT YOU DO NOT"):]
    assert guided.endswith(shared)


@pytest.mark.asyncio
async def test_guided_prompt_and_state(monkeypatch):
    first_line, has_state = "You are PAI, a counselor who stays", True
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=output("That sounds like a real turning point for you."))
        with patch("app.pai_c.deep.turn.chat_completion", model):
            await run_deep_turn(db, _turn(student), history=[], decision=COUNSEL)
        prompt = model.await_args.kwargs["system_prompt"]
        assert prompt.startswith(first_line)
        assert ("<state>" in prompt) is has_state


@pytest.mark.asyncio
async def test_state_block_content(monkeypatch):
    signals = fallback_signals().model_dump()
    signals.update(intent="asking_info", request={"text": "What does a data analyst do", "kind": "information",
                                                  "needs_research": False, "needs_context": False})
    with StudentSession() as student:
        prompts = []

        async def voice(**kwargs):
            prompts.append(kwargs["system_prompt"])
            return output("A data analyst turns raw numbers into answers people can use.")
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=json.dumps(signals))), \
                patch("app.pai_c.deep.turn.chat_completion", voice):
            await student.turn("What does a data analyst do")
            await student.turn("I like numbers")
        state = section(prompts[-1], "state")
        assert state["stage"] == "getting_to_know"
        assert set(state["areas"]) == {"status", "history", "interests", "strengths",
                                       "family_social", "values", "pressures", "sure", "goals", "options"}
        assert state["areas"]["history"] == {"covered": False, "item_count": 0, "min_items": 2}
        assert state["question_allowed"] is False and len(state["open_requests"]) <= 5
        assert state["last_moves"] and state["last_moves"][-1]["action"] == "answer_request"
        decision = section(prompts[-1], "decision")
        assert decision["action"] == "answer_request"
        assert decision["topic_text"] == "What does a data analyst do"
        with student.factory() as db:
            row = db.scalar(select(CounselorNotedQuestion))
            assert row.status == "answered_now"


@pytest.mark.asyncio
async def test_reply_repetition_guard_retries_once(monkeypatch):
    previous = "You enjoy building things with your hands and you want your parents to see that."
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": previous}]
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(side_effect=[output(previous), output("Tell me about a day when time flew by.")])
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student), history=history, decision=COUNSEL)
        assert model.await_count == 2 and "repeated_reply" in result.guard_violations
        assert result.reply == "Tell me about a day when time flew by."
        assert "Your draft repeats your previous reply." in model.await_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_reply_guard_keeps_second_draft_and_skips_care(monkeypatch):
    previous = "I am here with you, and what you feel matters."
    history = [{"role": "assistant", "content": previous}]
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(side_effect=[output(previous), output(previous)])
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student), history=history, decision=COUNSEL)
        assert model.await_count == 2 and result.reply == previous
        model = AsyncMock(return_value=output(previous, {"type": "wellbeing"}))
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student), history=history, instructions="wellbeing",
                                         safety_level="concern")
        assert model.await_count == 1 and "repeated_reply" not in result.guard_violations


@pytest.mark.asyncio
async def test_question_guard_still_enforced_in_guided_mode(monkeypatch):
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=output("That took courage. What happened next?"))
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student), history=[], decision=REST)
        assert result.reply == "That took courage." and "question_removed" in result.guard_violations
