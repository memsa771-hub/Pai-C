"""Core R1 request lifecycle and existing research compatibility, offline only."""
import importlib.util
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import CounselorNotedQuestion, EventRecord
from app.pai_c import runtime
from app.pai_c.deep.actions import dispatch_action
from app.pai_c.deep.context import build_context, DeepContext
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.deep.noted_questions import NotedQuestionService
from app.research.gateway import _research_brief
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_lean import source_turn


def reply_event(student, db, *, source="openagents:pai", workspace_id=None):
    event = EventRecord(id=str(uuid4()), network_id=workspace_id or student.workspace_id,
        type="workspace.message.posted", source=source, target="channel/pai-counselor",
        payload={"content": "An answer"}, timestamp=student.next_timestamp())
    db.add(event)
    db.commit()
    return event.id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [None, "information", "task", "decision_help", "other"])
async def test_request_kinds_and_defaults_persist_without_starting_research(kind):
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        action = {"type": "note_question", "question_to_research": "Help with this request"}
        if kind is not None:
            action["kind"] = kind
        context = DeepContext("", {}, CounselorNotebookData(), None, 0)
        executor = AsyncMock()
        with patch("app.tools.get_tool_executor", return_value=executor):
            assert await dispatch_action(db, turn, action, context) == ("note_question", "recorded")
        executor.execute.assert_not_awaited()
        row = db.scalar(sa.select(CounselorNotedQuestion))
        assert row.kind == (kind or "information")
        assert row.needs_research and row.status == "open" and row.answered_event_id is None


@pytest.mark.asyncio
async def test_answered_now_uses_actual_posted_reply_and_is_idempotent():
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        event = db.get(EventRecord, turn.source_event_id)
        event_data = {"id": event.id, "source": event.source, "target": event.target,
                      "timestamp": event.timestamp, "payload": event.payload, "metadata": {}}
        output = json.dumps({"reply": "Here is the help you asked for.", "moves": ["give"],
            "action": {"type": "note_question", "question_to_research": "Help with this task",
                       "kind": "task", "needs_research": False}})
        with patch("app.pai_c.deep.turn.chat_completion", AsyncMock(return_value=output)), \
             patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value='{"safety":{"level":"none","category":null},"intent":"sharing","emotion":"neutral","request":null,"mentioned_areas":[],"declined_area":null}')):
            posted = await runtime._run_deep_turn(db, student.workspace_id, event_data, 0)
        row = db.scalar(sa.select(CounselorNotedQuestion))
        assert row.status == "answered_now" and not row.needs_research and row.kind == "task"
        assert row.answered_event_id == posted[0]
        reply = db.get(EventRecord, row.answered_event_id)
        assert reply.source == "openagents:pai" and reply.payload["content"] == "Here is the help you asked for."
        assert NotedQuestionService(db).record(student.workspace_id, turn.source_event_id,
            "Help with this task", kind="task", needs_research=False,
            answered_event_id=row.answered_event_id) == "duplicate"
        assert len(db.scalars(sa.select(CounselorNotedQuestion)).all()) == 1


@pytest.mark.parametrize("invalid", ["missing", "student", "other_workspace"])
def test_immediate_answer_rejects_invalid_reply_provenance(invalid):
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        event_id = None
        if invalid == "student":
            event_id = turn.source_event_id
        if invalid == "other_workspace":
            from app.models import Workspace
            other = str(uuid4())
            db.add(Workspace(id=other, name="Other", status="active")); db.commit()
            event_id = reply_event(student, db, workspace_id=other)
        assert NotedQuestionService(db).record(student.workspace_id, turn.source_event_id,
            "Already helped", needs_research=False, answered_event_id=event_id) == "ignored"
        assert db.scalar(sa.select(CounselorNotedQuestion)) is None


@pytest.mark.parametrize("fields", [{"kind": "invalid"}, {"needs_research": "false"}, {"needs_research": 0}])
def test_invalid_request_metadata_does_not_create_a_row(fields):
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        assert NotedQuestionService(db).record(student.workspace_id, turn.source_event_id,
            "Request", **fields) == "ignored"
        assert db.scalar(sa.select(CounselorNotedQuestion)) is None


def seed_request(student, db, status, index, *, needs_research=True):
    turn = source_turn(student, db)
    row = CounselorNotedQuestion(workspace_id=student.workspace_id, source_event_id=turn.source_event_id,
        question_to_research=f"Request {index}", kind="decision_help", status=status,
        needs_research=needs_research, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index))
    db.add(row); db.commit()
    return row


@pytest.mark.asyncio
async def test_context_open_only_newest_five_and_workspace_isolated():
    with StudentSession() as student, student.factory() as db:
        turn = source_turn(student, db)
        for index in range(7):
            seed_request(student, db, "open", index)
        for index, status in enumerate(("answered_now", "answered", "unanswered", "handed_off", "dropped"), 10):
            seed_request(student, db, status, index)
        from app.models import Workspace
        other_id = str(uuid4())
        db.add(Workspace(id=other_id, name="Other", status="active")); db.commit()
        other_event = reply_event(student, db, source="human:other", workspace_id=other_id)
        db.add(CounselorNotedQuestion(workspace_id=other_id, source_event_id=other_event,
            question_to_research="Other private request", kind="other")); db.commit()
        text = (await build_context(db, student.workspace_id, turn)).text
        block = json.loads(text.split("<open_requests>")[1].split("</open_requests>")[0])
        assert block == [{"text": f"Request {index}", "kind": "decision_help"} for index in (6, 5, 4, 3, 2)]
        assert "Other private request" not in text


def test_answered_now_never_selected_for_research_and_legacy_statuses_unchanged():
    with StudentSession() as student, student.factory() as db:
        rows = [seed_request(student, db, status, index, needs_research=status != "answered_now")
                for index, status in enumerate(("open", "unanswered", "answered", "answered_now", "handed_off", "dropped"))]
        # Defensive filter even for an inconsistent historical/manual row.
        seed_request(student, db, "open", 10, needs_research=False)
        brief = _research_brief(db, student.workspace_id, SimpleNamespace(counselor_summary_draft={}),
            snapshot=SimpleNamespace(facts={}, records={}), understanding={"said": []})
        assert {row["id"] for row in brief["questions"]} == {rows[0].id, rows[1].id}
        assert [row.status for row in rows] == ["open", "unanswered", "answered", "answered_now", "handed_off", "dropped"]


def test_108_defaults_preserves_research_statuses_and_downgrade_columns():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    table = sa.Table("counselor_noted_questions", metadata,
        sa.Column("id", sa.Text(), primary_key=True), sa.Column("status", sa.Text(), nullable=False))
    metadata.create_all(engine)
    path = Path(__file__).parents[1] / "alembic/versions/108_counselor_request_intake.py"
    spec = importlib.util.spec_from_file_location("migration108", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.down_revision == "107"
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"id": status, "status": status} for status in ("open", "answered", "unanswered")])
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            rows = connection.execute(sa.text("SELECT * FROM counselor_noted_questions ORDER BY id")).mappings().all()
            assert all(row["kind"] == "information" and row["needs_research"] and row["answered_event_id"] is None for row in rows)
            assert all(row["id"] == row["status"] for row in rows)
            migration.downgrade()
            assert {column["name"] for column in sa.inspect(connection).get_columns("counselor_noted_questions")} == {"id", "status"}
            assert connection.scalar(sa.text("SELECT count(*) FROM counselor_noted_questions")) == 3
    engine.dispose()
