"""Collection reply review is shared by text and transcribed voice turns."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.counseling.reply_guard import (deterministic_issues, guard_collection_reply,
                                        guard_reply)
from scripts.eval_counselor_journey import check_reply_guard_scenarios


def test_collection_guard_keeps_allowed_reply():
    draft = "I can explain that. What are you studying now?"
    with patch("app.counseling.reply_guard.chat_completion",
               new=AsyncMock(return_value='{"allowed": true, "reply": "ignored"}')):
        result = asyncio.run(guard_collection_reply(
            draft, student_message="Tell me about engineering", question="What are you studying now?"))
    assert result == draft


def test_collection_guard_rewrites_personalized_draft():
    with patch("app.counseling.reply_guard.chat_completion",
               new=AsyncMock(return_value='{"allowed": false, "reply": "I can help explore that. What are you studying now?"}')):
        result = asyncio.run(guard_collection_reply(
            "You should apply to X", student_message="Should I apply?",
            question="What are you studying now?"))
    assert result == "I can help explore that. What are you studying now?"


def test_collection_guard_fails_closed_on_invalid_review():
    with patch("app.counseling.reply_guard.chat_completion",
               new=AsyncMock(return_value="not json")):
        result = asyncio.run(guard_collection_reply(
            "You will get into X", student_message="Will I?",
            question="What are you studying now?"))
    assert "You will get into X" not in result
    assert "What are you studying now?" in result


def test_deterministic_limits_catch_two_questions_and_long_drafts():
    assert "too_many_questions" in deterministic_issues("Where? When?")
    assert "too_long" in deterministic_issues("word " * 121)
    assert deterministic_issues("A short answer. What matters most?") == []


def test_known_or_pending_profile_question_cannot_be_reasked():
    for status in ("answered", "pending", "deferred"):
        fields = [{"status": status, "question": "What are you studying now?"}]
        assert "reasks_known_or_pending" in deterministic_issues(
            "I can help. What are you studying now?", requirement_fields=fields)


def test_open_reply_guard_rewrites_a_double_question():
    with patch("app.counseling.reply_guard.chat_completion",
               new=AsyncMock(return_value='{"allowed": false, "reply": "I can help. Which route matters more?"}')):
        result = asyncio.run(guard_reply(
            "Where? When?", student_message="Help me choose a route", mode="open"))
    assert result == "I can help. Which route matters more?"


def test_open_reply_guard_rejects_unsafe_rewrite():
    with patch("app.counseling.reply_guard.chat_completion",
               new=AsyncMock(return_value='{"allowed": false, "reply": "Where? When?"}')):
        result = asyncio.run(guard_reply(
            "Where? When?", student_message="Help me choose a route", mode="open"))
    assert result.count("?") <= 1


def test_offline_journey_scenarios_cover_reply_traps():
    assert all(check_reply_guard_scenarios().values())
