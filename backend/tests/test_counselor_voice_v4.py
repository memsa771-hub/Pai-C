"""Offline Voice contract, repetition repair and move storage checks."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.pai_c.policy.classifier import Signals, fallback_signals
from app.config import config
from app.models import CounselorTurnDecision, EventRecord
from app.pai_c.deep.turn import _parse_response, run_deep_turn
from app.pai_c.voice.guards import repeated_questions
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn


def answer(reply, moves=None, action=None):
    return json.dumps({'reply':reply, 'moves':moves or [], 'action':action or {'type':'none'}})


@pytest.mark.parametrize('moves,expected', [
    (['reflect','give','ask'],['reflect','give','ask']),
    (['reflect','unknown',None,{}],['reflect']),
    (None,[]), ('ask',[]),
])
def test_voice_parses_only_known_moves(moves, expected):
    assert _parse_response(answer('A reflection.',moves))[2] == expected
    assert _parse_response('{"reply":"A reflection."}')[2] == []


@pytest.mark.parametrize('old,new', [
    ('What did you enjoy doing?', 'What did you enjoy doing\uff1f'),
    ('Tum ko kya pasand hai?', 'tum ko kya pasand hai?!'),
    ('What project did you make?', 'What project did you make alone?'),
    ('What do you like doing?', 'What do you like doing\u061f'),
])
def test_guard_catches_near_duplicates_with_generic_tokens(old,new):
    assert repeated_questions(new,[{'role':'assistant','content':'You kept trying. '+old}])


def test_guard_ignores_different_questions_and_student_questions_and_respects_window():
    history=[{'role':'assistant','content':'What did you make?'},
             {'role':'user','content':'Who supported you?'}]
    assert not repeated_questions('Who supported you?',history)
    assert repeated_questions('What did you make?',[],['What did you make?'])
    with patch.object(config,'PAI_REPEAT_QUESTION_WINDOW',1):
        assert not repeated_questions('What did you make?',history+[{'role':'assistant','content':'Who supported you?'}])


@pytest.mark.asyncio
@pytest.mark.parametrize('retry,expected,violations', [
    ('You kept going. What did you enjoy doing?', 'You kept going.', ['repeated_question','repeat_removed']),
    ('What did you enjoy doing?', 'What did you enjoy doing?', ['repeated_question']),
    ('You kept going. Who supported you?', 'You kept going. Who supported you?', ['repeated_question']),
])
async def test_repeat_retries_once_then_removes_only_repeated_sentence(retry,expected,violations):
    with StudentSession() as student,student.factory() as db:
        model=AsyncMock(side_effect=[answer('What did you enjoy doing?',['ask']),answer(retry,['reflect','ask'])])
        with patch('app.pai_c.deep.turn.chat_completion',model):
            result=await run_deep_turn(db,_turn(student),history=[{'role':'assistant','content':'What did you enjoy doing?'}])
        assert model.await_count==2
        assert 'Your draft repeated a question already asked: What did you enjoy doing?. Do not ask it again.' in model.await_args.kwargs['system_prompt']
        assert result.reply==expected and result.guard_violations==violations
        assert result.moves==['reflect','ask']


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [True,False])
async def test_guard_never_runs_for_wellbeing(explicit):
    with StudentSession() as student,student.factory() as db:
        model=AsyncMock(return_value=answer('What did you enjoy doing?',action={'type':'none' if explicit else 'wellbeing'}))
        with patch('app.pai_c.deep.turn.chat_completion',model),patch('app.pai_c.voice.guards.repeated_questions',side_effect=AssertionError('no guard')):
            result=await run_deep_turn(db,_turn(student),history=[{'role':'assistant','content':'What did you enjoy doing?'}],instructions='wellbeing' if explicit else None)
        assert model.await_count==1 and result.guard_violations==[]


@pytest.mark.asyncio
async def test_guard_respects_plan_avoid_questions():
    from app.models import PaiTurnPlan
    from tests.test_counselor_deep_pr4 import _turn_job
    from scripts.eval.recorded_planner import PLAN
    with StudentSession() as student,student.factory() as db:
        _,event_id=_turn_job(student,db)
        db.add(PaiTurnPlan(workspace_id=student.workspace_id,source_event_id=event_id,notebook_version=1,plan={**PLAN,'avoid_questions':['Who supported you?']}));db.commit()
        model=AsyncMock(side_effect=[answer('Who supported you?'),answer('You already described that support.')])
        with patch('app.pai_c.deep.turn.chat_completion',model):
            result=await run_deep_turn(db,_turn(student),history=[])
        assert model.await_count==2 and result.guard_violations==['repeated_question']


def test_migration_106_adds_nullable_moves_and_downgrade_preserves_decisions():
    path=Path(__file__).parents[1]/'alembic/versions/106_counselor_voice_moves.py'
    spec=importlib.util.spec_from_file_location('voice_moves_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    assert migration.revision=='106' and migration.down_revision=='105'
    with StudentSession() as student,student.factory() as db:
        db.execute(sa.text('ALTER TABLE pai_counselor_turn_decisions DROP COLUMN moves'));db.commit()
        with patch.object(migration,'op',Operations(MigrationContext.configure(db.connection()))):
            migration.upgrade()
            assert next(row for row in sa.inspect(db.connection()).get_columns('pai_counselor_turn_decisions') if row['name']=='moves')['nullable']
            db.add(CounselorTurnDecision(workspace_id=student.workspace_id,source_event_id='event',source_timestamp=1,move='none',moves=['reflect','give'],guard_violations=[]));db.flush()
            migration.downgrade()
        assert db.scalar(sa.text('SELECT COUNT(*) FROM pai_counselor_turn_decisions'))==1


@pytest.mark.asyncio
async def test_runtime_stores_moves_and_repetition_violations_and_logs_no_question_text(caplog):
    from app.pai_c import runtime
    from tests.test_counselor_deep_pr4 import _turn_job
    with StudentSession() as student,student.factory() as db:
        _,event_id=_turn_job(student,db)
        event=db.get(EventRecord,event_id)
        data={'id':event.id,'source':event.source,'target':event.target,'timestamp':event.timestamp,'payload':event.payload,'metadata':{}}
        model=AsyncMock(side_effect=[answer('What did you enjoy doing?',['ask']),answer('You kept going. What did you enjoy doing?',['reflect','ask'])])
        history=[{'role':'assistant','content':'What did you enjoy doing?'}]
        with patch.object(config,'PAI_API_KEY','fake'),patch('app.pai_c.memory.MemoryService.recent_turns',return_value=history),patch('app.pai_c.policy.classifier.classify',AsyncMock(return_value=Signals.model_validate({**fallback_signals().model_dump(), 'question_needed': True}))),patch('app.pai_c.deep.turn.chat_completion',model),caplog.at_level('INFO',logger='app.pai_c.runtime'):
            await runtime._run_deep_turn(db,student.workspace_id,data,0)
        row=db.scalar(sa.select(CounselorTurnDecision))
        assert row.moves==['reflect','ask'] and row.guard_violations==['repeated_question','repeat_removed']
        logs=[record.message for record in caplog.records if 'counselor_deep_turn' in record.message]
        assert logs and "moves=['reflect', 'ask']" in logs[0]
        assert 'What did you enjoy' not in logs[0]


@pytest.mark.asyncio
async def test_combined_guards_keep_one_language_retry_for_the_whole_turn():
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(side_effect=[answer('\u03b1?'),
            answer('What did you enjoy doing?'), answer('\u03b2?')])
        with patch('app.pai_c.deep.turn.chat_completion', model), \
                patch.object(config, 'PAI_LANGUAGE_BLOCKED_SCRIPTS', 'Greek'):
            result = await run_deep_turn(db, _turn(student),
                history=[{'role':'assistant','content':'What did you enjoy doing?'}])
        assert model.await_count == 2
        assert result.reply == 'What did you enjoy doing?'
        assert result.guard_violations == ['repeated_question']
