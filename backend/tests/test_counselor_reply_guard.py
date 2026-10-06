"""Collection reply review is shared by text and transcribed voice turns."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.counseling.reply_guard import guard_collection_reply


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
