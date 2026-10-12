"""Offline versioned playbook data and Planner/Voice integration."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models import PaiTurnPlan
from app.pai_c.deep.analysis import analyze_job
from app.pai_c.deep.context import build_context
from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.playbooks.registry import BOOKS, load_registry
from app.pai_c.planner.plan import validate_plan
from scripts.counselor_eval_support import StudentSession
from scripts.eval.recorded_planner import PLAN
from tests.test_counselor_deep_pr3 import _turn
from tests.test_counselor_deep_pr4 import _turn_job


def write_book(folder, filename='one.md', id='one', when='A moment.', body='A useful response.',version=1):
    (folder/filename).write_text('---\nid: '+id+'\nversion: '+str(version)+'\nwhen: '+json.dumps(when)+'\n---\n'+body,encoding='utf-8')


@pytest.mark.parametrize('when,body,version', [('', 'Body.',1), ('Moment.','',1), ('Moment.','word '*121,1), ('Moment.','Body.',2)])
def test_registry_rejects_invalid_files(tmp_path,when,body,version):
    write_book(tmp_path,when=when,body=body,version=version)
    with pytest.raises(ValueError):load_registry(tmp_path)


def test_registry_rejects_duplicate_ids_and_bad_frontmatter(tmp_path):
    write_book(tmp_path);write_book(tmp_path,'two.md')
    with pytest.raises(ValueError):load_registry(tmp_path)
    (tmp_path/'two.md').unlink();(tmp_path/'one.md').write_text('Body only.')
    with pytest.raises(ValueError):load_registry(tmp_path)


def test_registry_loads_exact_when_and_body_and_is_immutable(tmp_path):
    write_book(tmp_path,body='A useful response.\n')
    books=load_registry(tmp_path)
    assert books['one'].when=='A moment.' and books['one'].body=='A useful response.\n'
    with pytest.raises(TypeError):books['two']=books['one']
    assert len(BOOKS)==10 and all(len(book.body.split())<=120 for book in BOOKS.values())


@pytest.mark.parametrize('ids', [['impatient'],['impatient','short_answers'],[]])
def test_plan_accepts_up_to_two_registered_playbooks(ids):
    assert validate_plan({**PLAN,'playbooks':ids}).playbooks==ids


@pytest.mark.parametrize('ids', [['unknown'],['impatient','short_answers','returning']])
def test_plan_rejects_unknown_or_more_than_two_playbooks(ids):
    with pytest.raises(ValueError):validate_plan({**PLAN,'playbooks':ids})


@pytest.mark.asyncio
async def test_planner_receives_available_playbooks_and_stores_selection():
    with StudentSession() as student,student.factory() as db:
        job,_=_turn_job(student,db)
        model=AsyncMock(return_value=json.dumps({'patch':[],'plan':{**PLAN,'playbooks':['impatient']}}))
        with patch('app.pai_c.deep.analysis.chat_completion',model):
            await analyze_job(job,db)
        system=model.await_args.kwargs['system_prompt']
        block=json.loads(system.rsplit('<available_playbooks>',1)[1].split('</available_playbooks>')[0])
        assert len(block)==10 and set(block[0])=={'id','when'}
        assert BOOKS['impatient'].when in system
        assert 'Choose at most two playbooks that fit the student right now, or none.' in system
        assert db.query(PaiTurnPlan).one().plan['playbooks']==['impatient']


@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [[],['impatient'],['impatient','short_answers']])
async def test_context_includes_only_selected_playbook_bodies(ids):
    with StudentSession() as student,student.factory() as db:
        _,event_id=_turn_job(student,db)
        db.add(PaiTurnPlan(workspace_id=student.workspace_id,source_event_id=event_id,notebook_version=1,plan={**PLAN,'playbooks':ids}));db.commit()
        context=await build_context(db,student.workspace_id,_turn(student))
        assert ('<playbooks>' in context.text)==bool(ids)
        if ids:
            block=json.loads(context.text.split('<playbooks>')[1].split('</playbooks>')[0])
            assert [row['id'] for row in block]==ids
            assert all(row['body']==BOOKS[row['id']].body for row in block)
            assert BOOKS['setback'].body not in context.text


@pytest.mark.asyncio
async def test_wellbeing_model_never_receives_playbooks():
    with StudentSession() as student,student.factory() as db:
        _,event_id=_turn_job(student,db)
        db.add(PaiTurnPlan(workspace_id=student.workspace_id,source_event_id=event_id,notebook_version=1,plan={**PLAN,'playbooks':['impatient']}));db.commit()
        model=AsyncMock(return_value=json.dumps({'reply':'I am here with you.','moves':['reflect'],'action':{'type':'wellbeing'}}))
        with patch('app.pai_c.deep.turn.chat_completion',model):
            await run_deep_turn(db,_turn(student),instructions='wellbeing',history=[])
        prompt = model.await_args.kwargs['system_prompt']
        context = prompt.split('<context>',1)[1].split('</context>',1)[0]
        assert '<playbooks>' not in context
        assert BOOKS['impatient'].body not in prompt


def test_each_playbook_has_a_short_generic_replay_fixture():
    folder=Path(__file__).parent/'fixtures/playbooks'
    assert {path.stem for path in folder.glob('*.json')}==set(BOOKS)
    for id in BOOKS:
        fixture=json.loads((folder/(id+'.json')).read_text())
        assert fixture['playbook']==id
        assert 3<=len(fixture['conversation'])<=4
        assert [row['role'] for row in fixture['conversation']]==['user','assistant','user','assistant']
        assert all(row['content'].strip() for row in fixture['conversation'])
