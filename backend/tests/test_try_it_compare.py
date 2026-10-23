"""Guide artifacts and normal feedback intake, with fake providers only."""
import json
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from app.pai_c.deep.roadmaps import TryIt, RoadmapCandidate
from app.pai_c.deep.context import build_context
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.pai_c.policy.controller import decide
from app.pai_c.roadmaps.service import RoadmapService
from app.models import EventRecord, RoadmapStudentState
from scripts.counselor_eval_support import StudentSession
from tests.test_conversation_policy import state
from tests.test_roadmaps import _journey, _card


@pytest.mark.parametrize('kind,count,valid', [('talk_to_someone',3,True),('talk_to_someone',2,False),
    ('talk_to_someone',4,False),('taste_the_work',0,True),('taste_the_work',1,False)])
def test_try_it_question_contract(kind,count,valid):
    value={'kind':kind,'what':'Try this activity','time_needed':'One evening','questions':['A useful question?']*count}
    if valid: assert TryIt.model_validate(value).kind==kind
    else:
        with pytest.raises(ValueError): TryIt.model_validate(value)


def test_generation_requires_try_it_and_prompts_match_contract():
    with pytest.raises(ValueError): RoadmapCandidate.model_validate({'test_30_days':'Old activity'})
    prompt=load_prompt('roadmap_builder')
    assert 'test_30_days' not in prompt and 'TRY IT: give each roadmap one small way' in prompt
    assert prompt.split('TRUTH MAP INPUT')[1]==load_prompt('mirror').split('TRUTH MAP INPUT')[1]
    assert "update sure only if they give a number." in load_prompt('planner')


def test_old_saved_roadmap_remains_readable_without_rewrite():
    with StudentSession() as student,student.factory() as db:
        journey=_journey(db,student.workspace_id);row=_card(db,student.workspace_id,journey.id,'Old route')
        row.route={'counselor_fit':{'test_30_days':'The original saved activity'}};db.commit()
        saved=RoadmapService(db).get(student.workspace_id,row.id)
        assert saved['test_30_days']=='The original saved activity' and 'try_it' not in saved
        assert row.route=={'counselor_fit':{'test_30_days':'The original saved activity'}}


@pytest.mark.asyncio
async def test_guide_compare_contains_published_fit_only_with_limit_and_exclusions(monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, "PAI_POLICY_MODE", "strict")
    with StudentSession() as student,student.factory() as db:
        journey=_journey(db,student.workspace_id)
        for index in range(8):
            row=_card(db,student.workspace_id,journey.id,f'Route {index}')
            row.route={'counselor_fit':{'why_for_you':'Your evidence','strengths_used':['Practice'],
                'family_fit':'Your stated support','constraints_fit':'Your stated time',
                'try_it':{'kind':'taste_the_work','what':'A small task','time_needed':'An evening','questions':[]},
                'facts':[{'text':'A cited fact','label':'unconfirmed'}]}}
            row.gaps=[{'need':'Published need','have':'Student experience','gap':'Published gap'}]
            row.risks=['Published risk'];row.sources=[{'url':'https://example.test/source','status':'verified'}]
            if index==6: RoadmapService(db).dismiss(student.workspace_id,row.id,True)
            if index==7: row.generation_status='stale'
        db.commit()
        turn=CounselorTurnInput('channel/pai-counselor',student.workspace_id,'Compare these',(),None,'turn',1,'human:student')
        decision=decide(state(intent='deciding'))
        context=await build_context(db,student.workspace_id,turn,decision=decision)
        compare=json.loads(context.text.split('<compare>')[1].split('</compare>')[0])
        assert len(compare)==5
        assert not {'Route 6','Route 7'} & {row['title'] for row in compare}
        row=compare[0]
        assert set(row)=={'title','origin','why_for_you','strengths_used','family_fit','constraints_fit',
            'risks','gaps','try_it','favorite','focused','facts','source_labels'}
        assert row['facts'][0]['label']=='unconfirmed' and row['source_labels'][0]['label']=='verified'
        assert row['gaps'][0]=={'need':'Published need','have':'Student experience','gap':'Published gap'}
        assert context.text.index('<research>') < context.text.index('<compare>') < context.text.index('</research>')
        normal=await build_context(db,student.workspace_id,turn,decision=decide(state()))
        assert '<compare>' not in normal.text


def test_try_it_message_uses_normal_event_path_and_reaches_planner_without_dismissal():
    from app.main import app
    from app.database import get_db
    from app.pai_c.deep.analysis import _input
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from tests.test_counselor_mirror import client_for
    with StudentSession() as student,student.factory() as db:
        journey=_journey(db,student.workspace_id);roadmap=_card(db,student.workspace_id,journey.id,'Practical route');db.commit()
        async def persist(event,context):
            context.extra['db'].add(EventRecord(id=event.id,network_id=event.network,type=event.type,
                source=event.source,target=event.target,payload=event.payload,metadata_=event.metadata,timestamp=event.timestamp))
            return event
        client=client_for(student)
        try:
            with patch('app.security.event_identity.verify_identity_claims',return_value={'session_user_id':student.user_id}), \
                 patch('app.routers.events.pipeline.process',AsyncMock(side_effect=persist)), \
                 patch('app.pai_c.orchestrator.handle_student_message',AsyncMock()) as counselor, \
                 patch('app.services.workflow.advance_workflow'),patch('app.services.integrations.relay_for_event'), \
                 patch('app.infrastructure.cache.publish_event'),patch('app.routers.events._invalidate_poll_cache'):
                result=client.post('/v1/events',json={'network':student.workspace_id,'type':'workspace.message.posted',
                    'target':'channel/pai-counselor','payload':{'content':'Practical route, Try it: Not for me. I tried the small task.','message_type':'chat'},
                    'metadata':{'target_agents':['pai'],'try_it_roadmap_id':roadmap.id}},
                    headers={'X-Workspace-Token':'synthetic-test-only','Authorization':'Bearer offline-owner-id-token'})
            assert result.status_code==200,result.text
            counselor.assert_awaited_once()
            db.expire_all();event=db.get(EventRecord,result.json()['data']['id'])
            assert event.metadata_['try_it_roadmap_id']==roadmap.id
            assistant=EventRecord(id=str(uuid4()),network_id=student.workspace_id,type='workspace.message.posted',
                source='openagents:pai',target=event.target,payload={'content':'Thanks for sharing.'},timestamp=event.timestamp+1)
            db.add(assistant);db.commit()
            planner_input=_input(db,student.workspace_id,event,assistant,CounselorNotebookData())
            assert event.payload['content'] in planner_input
            assert db.scalar(select(RoadmapStudentState).where(RoadmapStudentState.roadmap_id==roadmap.id)).dismissed_at is None
        finally: app.dependency_overrides.pop(get_db,None)
