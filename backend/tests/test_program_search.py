"""Explicit H gate and conservative evidence-based eligibility."""
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from app.pai_c.paths.programs import eligibility
from app.pai_c.possibilities import PossibilityService
from app.models import ExecutionRun
from app.research.gateway import request_research
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_lean import research_journey
from types import SimpleNamespace


@pytest.mark.parametrize('level,label',[('stated','unknown'),('shown','eligible'),('confirmed','eligible')])
def test_merit_never_uses_stated_numbers(level,label):
    rule={'field':'result.score','value':60,'comparator':'gte','threshold':60,
        'source_url':'https://example.edu/rules','checked_at':datetime.now(timezone.utc).isoformat()}
    result=eligibility({'status':'verified','rules':[rule]}, {'result.score':{'value':80,'evidence_level':level}})
    assert result['label']==label
    assert eligibility({'status':'unconfirmed','rules':[rule]}, {'result.score':{'value':80,'evidence_level':level}})['label']=='unknown'


def test_not_yet_routes_only_from_sourced_rule_no_chance_guess():
    rule={'field':'result.score','value':60,'comparator':'gte','threshold':60,
        'source_url':'https://example.edu/rules','checked_at':datetime.now(timezone.utc).isoformat(),
        'remediation':{'action':'Complete prerequisite','source_url':'https://example.edu/preparation'}}
    result=eligibility({'status':'verified','rules':[rule]}, {'result.score':{'value':40,'evidence_level':'confirmed'}})
    assert result['label']=='not_yet' and result['route']==[rule['remediation']]


@pytest.mark.asyncio
async def test_program_search_requires_completed_current_path():
    with StudentSession() as student, student.factory() as db:
        journey=research_journey(student,db)
        row=PossibilityService(db).add(student.workspace_id,journey.id,title='Practical design',why='Evidence',
            kind='discovered',source='planner',status='exploring')
        db.commit()
        assert await request_research('program_search',student.workspace_id,db=db,journey=journey,
            tool_context=SimpleNamespace(workspace_id=student.workspace_id),possibility_id=row.id) is None
        db.add(ExecutionRun(workspace_id=student.workspace_id,requested_by='pai',task_type='path_explain',
            objective='Explore',status='completed',constraints={'possibility_id':row.id,'vault_version':'an-older-vault'}))
        db.commit()
        assert await request_research('program_search',student.workspace_id,db=db,journey=journey,
            tool_context=SimpleNamespace(workspace_id=student.workspace_id),possibility_id=row.id) is None


def test_program_read_rechecks_current_evidence_and_expired_sources():
    from datetime import timedelta
    from app.models import Opportunity, RequirementSet
    from app.pai_c.paths.programs import current_programs
    with StudentSession() as student, student.factory() as db:
        opportunity = Opportunity(workspace_id=student.workspace_id, route={}, country='Student place', url='https://example.edu/rules')
        db.add(opportunity); db.flush()
        row = RequirementSet(opportunity_id=opportunity.id, version=1, status='verified',
            source_url=opportunity.url, checked_at=datetime.now(timezone.utc),
            rules=[{'field':'result.score','comparator':'gte','threshold':60,'value':60,
                    'source_url':opportunity.url,'quote':'Entry threshold'}], fees={}, deadlines={})
        db.add(row); db.commit()
        result={'programs':[{'opportunity_id':opportunity.id,'title':'A program','eligibility':{'label':'eligible'}}]}
        current, stale=current_programs(db, student.workspace_id, result, {'result.score':{'value':40,'evidence_level':'confirmed'}})
        assert not stale and current['programs'][0]['eligibility']['label']=='not_yet'
        current,_=current_programs(db, student.workspace_id, result, {'result.score':{'value':80,'evidence_level':'stated'}})
        assert current['programs'][0]['eligibility']['label']=='unknown'
        row.checked_at=datetime.now(timezone.utc)-timedelta(days=1000); db.flush()
        current,stale=current_programs(db,student.workspace_id,result,{})
        assert stale and not current['programs'] and 'expired_sources' in current['missing']
        foreign,stale=current_programs(db,'other-workspace',result,{})
        assert stale and not foreign['programs']


@pytest.mark.asyncio
async def test_expired_program_run_refreshes_once_and_pending_run_is_reused():
    from datetime import timedelta
    from unittest.mock import AsyncMock
    with StudentSession() as student, student.factory() as db:
        journey=research_journey(student,db)
        row=PossibilityService(db).add(student.workspace_id,journey.id,title='Practical design',why='Evidence',kind='discovered',source='planner',status='exploring')
        route=PossibilityService(db).research_route(row)
        from app.memory.completeness import vault_version
        version=vault_version(db,student.workspace_id)
        db.add(ExecutionRun(workspace_id=student.workspace_id,requested_by='pai',task_type='path_explain',objective='Explain',status='completed',constraints={'possibility_id':row.id,'vault_version':version}))
        old=ExecutionRun(workspace_id=student.workspace_id,requested_by='pai',task_type='program_search',objective='Search',status='completed',created_at=datetime.now(timezone.utc)-timedelta(days=1000),constraints={'possibility_id':row.id,'vault_version':version,'capability_input':{'brief':{'route':route}}},result={'capability_result':{'programs':[]}})
        db.add(old);db.commit()
        async def queue(payload, context):
            run=ExecutionRun(workspace_id=student.workspace_id,requested_by='pai',task_type='program_search',objective='Search',status='pending',constraints=payload['constraints'])
            db.add(run);db.commit()
            return {'ok':True,'data':{'run_id':run.id,'status':'pending'}}
        with patch('app.research.gateway._delegate',side_effect=queue) as delegate:
            kwargs=dict(db=db,journey=journey,tool_context=SimpleNamespace(workspace_id=student.workspace_id),possibility_id=row.id)
            first=await request_research('program_search',student.workspace_id,**kwargs)
            second=await request_research('program_search',student.workspace_id,**kwargs)
            assert first['data']['run_id']==second['data']['run_id'] and delegate.call_count==1
            assert ':refresh:'+old.id in delegate.call_args.args[0]['constraints']['research_key']


def test_changed_student_route_invalidates_completed_program_run():
    from app.pai_c.paths.programs import reusable_program_run
    run=SimpleNamespace(constraints={'capability_input':{'brief':{'route':{'place_preference':'Earlier place'}}}},status='completed')
    assert not reusable_program_run(None,run,{'place_preference':'New place'})
