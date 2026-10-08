"""Shared deep turn input, prompts and successful-post learning hooks."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.config import config
from app.counseling import runtime
from app.counseling.deep.polish import (
    contains_blocked_script, has_list, question_count, polish_reply,
)
from app.counseling.deep.prompts import load_prompt
from app.counseling.deep.turn_input import CounselorTurnInput, _returning, shared_history
from app.memory.turn_hook import enqueue_turn_extraction
from app.models import EventRecord
from scripts.counselor_eval_support import StudentSession


@pytest.mark.asyncio
async def test_deep_queues_learning_after_successful_human_post():
    event = {"id": "student-event", "source": "human:student", "target": "channel/pai"}
    deep = AsyncMock(return_value=("assistant-event", "channel/pai", False))
    with patch.object(runtime, "_run_deep_turn", deep), \
            patch("app.counseling.deep.analysis.enqueue_turn_analysis") as analyze, \
            patch("app.memory.turn_hook.enqueue_turn_extraction") as enqueue:
        await runtime._run_turn(Mock(), "workspace", event, 0)
    assert deep.await_count == 1
    analyze.assert_called_once()
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["user_event_id"] == "student-event"
    assert enqueue.call_args.kwargs["assistant_event_id"] == "assistant-event"


@pytest.mark.asyncio
@pytest.mark.parametrize("source,posted", [
    ("human:student", None), ("openagents:pai", ("assistant-event", "channel/pai", False)),
])
async def test_extraction_requires_a_successful_human_turn(source, posted):
    with patch.object(runtime, "_run_deep_turn", new=AsyncMock(return_value=posted)), \
            patch("app.memory.turn_hook.enqueue_turn_extraction") as enqueue:
        await runtime._run_turn(Mock(), "workspace", {"id": "event", "source": source}, 0)
    enqueue.assert_not_called()



def test_retry_of_same_student_event_uses_one_extraction_key():
    db = Mock()
    service = Mock()
    service.enqueue.return_value.id = "job-1"
    with patch("app.memory.turn_hook.BackgroundJobService", return_value=service):
        for assistant_id in ("reply-1", "reply-2"):
            assert enqueue_turn_extraction(
                db, "workspace", "channel/pai", "student-1", assistant_id, "pai",
            ) == "job-1"
    keys = [call.kwargs["idempotency_key"] for call in service.enqueue.call_args_list]
    assert keys == ["extract:turn:student-1"] * 2


def test_shared_history_crosses_chat_and_voice_without_future_leak():
    with StudentSession() as student, student.factory() as db:
        base = student.next_timestamp()
        for offset, source, target, text in (
            (0, f"human:{student.user_id}", "channel/chat", "I finished FSc"),
            (1, "openagents:pai", "channel/chat", "Which group?"),
            (2, f"human:{student.user_id}", "channel/voice", "Pre-Engineering"),
            (4, f"human:{student.user_id}", "channel/chat", "future message"),
        ):
            db.add(EventRecord(
                id=str(uuid.uuid4()), network_id=student.workspace_id,
                type="workspace.message.posted", source=source, target=target,
                payload={"content": text}, timestamp=base + offset,
            ))
        db.commit()
        turn = CounselorTurnInput("channel/chat", student.workspace_id, "What's next?",
                                  (), "chat-2", "trigger", base + 3,
                                  f"human:{student.user_id}")
        history = shared_history(db, turn, str(student.user_id))
        assert [row["content"] for row in history] == [
            "I finished FSc", "Which group?", "Pre-Engineering",
        ]
        assert _returning(history, turn) is True


def test_moved_reply_checks_and_prompt_files():
    assert polish_reply("Tell me more? How long?") == "Tell me more?"
    assert question_count("What did you do? How long?") == 2
    assert has_list("- A route\n- Another route")
    assert contains_blocked_script("α", "Greek")
    assert not contains_blocked_script("a", "Greek")
    for name in ("counselor", "analyst", "mirror", "roadmap_builder", "sensitive_check", "language_retry"):
        assert load_prompt(name).strip()
    with pytest.raises(ValueError, match="Unknown Counselor prompt"):
        load_prompt("other")

    source = Path(__file__).resolve().parents[2] / "docs/counselor/COUNSELOR_V3_PROMPTS.md"
    if source.is_file():
        import re
        document = source.read_text(encoding="utf-8")
        for name in ("counselor", "analyst", "mirror", "roadmap_builder"):
            match = re.search(
                rf"(?s)## [1-4]\. `{name}\.md`.*?```text\n(.*?)\n```", document,
            )
            assert match and load_prompt(name) == match.group(1) + "\n"
