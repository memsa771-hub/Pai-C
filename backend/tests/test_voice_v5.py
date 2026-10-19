"""Controller-to-Voice contracts, one retry and code-owned request intake."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select

from app.config import config
from app.models import CounselorNotedQuestion, CounselorTurnDecision
from app.pai_c.policy.classifier import fallback_signals
from app.pai_c.policy.controller import Decision
from app.pai_c.deep.turn import run_deep_turn
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn


@pytest.fixture(autouse=True)
def strict_policy_mode(monkeypatch):
    """These contracts describe the strict decision table."""
    monkeypatch.setattr(config, "PAI_POLICY_MODE", "strict")


def output(reply, action=None):
    return json.dumps({"reply":reply,"moves":["reflect"],"action":action or {"type":"none"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("drafts,expected,calls,violation",[
    (["I hear the effort. What next?"],"I hear the effort.",1,"question_removed"),
    (["What next?","I hear the effort."],"I hear the effort.",2,"question_retry"),
    (["What next?","What matters?"],None,2,"statement_fallback"),
])
async def test_question_guard_and_bounded_retry(drafts,expected,calls,violation):
    with StudentSession() as student,student.factory() as db:
        model=AsyncMock(side_effect=[output(reply) for reply in drafts])
        with patch("app.pai_c.deep.turn.chat_completion",model):
            result=await run_deep_turn(db,_turn(student),history=[],
                decision=Decision("listen","listen_reflect",None,False,False,False))
        assert model.await_count==calls and result.reply==(expected or config.PAI_STATEMENT_FALLBACK_REPLY)
        assert violation in result.guard_violations and "?" not in result.reply
        if calls==2:assert "Do not ask any question in this reply." in model.await_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_classifier_request_is_stored_before_voice_and_answered_once_after_post():
    signals=fallback_signals().model_dump()
    signals.update(intent="asking_task",request={"text":"Help me organize my notes","kind":"task","needs_research":False,"needs_context":False})
    with StudentSession() as student:
        async def voice(**kwargs):
            with student.factory() as db:
                row=db.scalar(select(CounselorNotedQuestion))
                assert row.status=="open" and row.answered_event_id is None
            context=kwargs["system_prompt"]
            decision=json.loads(context.rsplit("<context>",1)[1].split("<decision>",1)[1].split("</decision>")[0])
            assert decision["action"]=="answer_request" and not decision["question_allowed"]
            assert "invite them once" not in decision["instruction"]
            assert decision["insight_candidate"]=="" and "<plan>" not in context
            return output("Group your notes by topic.",{"type":"note_question","question_to_research":"duplicate","needs_research":False})
        with patch("app.pai_c.policy.classifier.complete",AsyncMock(return_value=json.dumps(signals))),patch("app.pai_c.deep.turn.chat_completion",voice):
            await student.turn("Help me organize my notes")
        with student.factory() as db:
            rows=db.scalars(select(CounselorNotedQuestion)).all()
            assert len(rows)==1 and rows[0].status=="answered_now" and rows[0].answered_event_id
            decision=db.scalar(select(CounselorTurnDecision)).decision
            assert decision["topic"]=="request" and decision["signals"]["needs_research"] is False
            assert "notes" not in json.dumps(decision)


@pytest.mark.asyncio
async def test_statement_fallback_posted_and_logged():
    signals=fallback_signals().model_dump();signals["emotion"]="stressed"
    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete",AsyncMock(return_value=json.dumps(signals))),patch("app.pai_c.deep.turn.chat_completion",AsyncMock(side_effect=[output("First?"),output("Second?")])):
            await student.turn("A difficult day")
        assert student.transcript[-1]["content"]==config.PAI_STATEMENT_FALLBACK_REPLY
        with student.factory() as db:
            row=db.scalar(select(CounselorTurnDecision))
            assert "statement_fallback" in row.guard_violations and row.decision["statement_fallback"] is True


@pytest.mark.parametrize("mark",["?","\u061f","\uff1f","\u00bf"])
def test_statement_fallback_rejects_unicode_questions(mark):
    with patch.object(config,"PAI_STATEMENT_FALLBACK_REPLY","Statement"+mark):
        with pytest.raises(RuntimeError,match="PAI_STATEMENT_FALLBACK_REPLY"):
            config.validate_startup()


def test_migration_109_upgrade_downgrade():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[1]/"alembic/versions/109_counselor_value_decision.py"
    spec=importlib.util.spec_from_file_location("migration109",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    assert migration.down_revision=="108"
    engine=sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE pai_counselor_turn_decisions (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO pai_counselor_turn_decisions VALUES ('existing')"))
        with patch.object(migration,"op",Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            assert connection.scalar(sa.text("SELECT decision FROM pai_counselor_turn_decisions")) is None
            migration.downgrade()
        assert connection.scalar(sa.text("SELECT id FROM pai_counselor_turn_decisions"))=="existing"
    engine.dispose()
