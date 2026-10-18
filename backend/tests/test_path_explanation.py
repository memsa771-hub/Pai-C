"""Stage G uses an isolated, durable workflow, not program discovery."""
import json
from unittest.mock import patch
import pytest
from sqlalchemy import select
from app.models import ExecutionRun, BackgroundJob
from app.pai_c.paths.explain import validate_explanation
from app.pai_c.possibilities import PossibilityService
from app.research.gateway import request_research
from app.tools import ToolContext, AUDIENCE_COUNSELOR
from app.services import operator
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_lean import research_journey


def explanation():
    return dict(what_it_is='A direction to investigate', what_you_study=['Methods'],
        work_day='Work varies by role', skills=['Practice'], fit_for=[{'observation':'An interest to test',
        'evidence':'I enjoy making things'}], fit_against=[], ways_in=['Explore a course outline'],
        try_it='Try a small project', world_facts=[])


def test_fit_requires_actual_student_quote_and_strict_output():
    brief={'evidence':[{'text':'I enjoy making things'}]}
    assert validate_explanation(json.dumps(explanation()),brief).fit_for
    with pytest.raises(ValueError): validate_explanation(json.dumps(explanation()),{'evidence':[]})
    with pytest.raises(ValueError): validate_explanation(json.dumps({**explanation(),'university':'Invented'}),brief)


@pytest.mark.asyncio
async def test_path_workflow_queued_once_and_confirmation_does_not_search_places():
    with StudentSession() as student, student.factory() as db:
        journey=research_journey(student,db,confirmed=True)
        ctx=ToolContext(student.workspace_id,'pai',None,conversation='pai-counselor',
            allowed_tools=frozenset({'operator.delegate'}),audience=AUDIENCE_COUNSELOR,
            granted_capabilities=frozenset({'web.read','operator.delegate'}))
        confirmed=await request_research('roadmap_light',student.workspace_id,db=db,journey=journey,tool_context=ctx,trigger='mirror_confirmed')
        assert confirmed['data']['status']=='paths_ready'
        assert not db.scalars(select(ExecutionRun)).all()
        row=PossibilityService(db).add(student.workspace_id,journey.id,title='Practical design',
            why='Student evidence',kind='discovered',source='planner',status='exploring')
        db.commit()
        from app.memory.permissions import capabilities_for_agent
        from dataclasses import replace
        ctx=replace(ctx,granted_capabilities=capabilities_for_agent('pai'))
        with patch.object(operator,'is_available',return_value=True):
            first=await request_research('path_explain',student.workspace_id,db=db,journey=journey,tool_context=ctx,possibility_id=row.id)
            again=await request_research('path_explain',student.workspace_id,db=db,journey=journey,tool_context=ctx,possibility_id=row.id)
        assert first['ok'] and first['data']['run_id']==again['data']['run_id']
        run=db.get(ExecutionRun,first['data']['run_id'])
        assert run.task_type=='path_explain'
        assert run.constraints['capability_input']['brief']['title']==row.title
        assert len(db.scalars(select(BackgroundJob).where(BackgroundJob.job_type=='operator.run')).all())==1
