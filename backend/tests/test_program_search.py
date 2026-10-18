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
        journey=research_journey(student,db,confirmed=True)
        row=PossibilityService(db).add(student.workspace_id,journey.id,title='Practical design',why='Evidence',
            kind='discovered',source='planner',status='exploring')
        db.commit()
        assert await request_research('program_search',student.workspace_id,db=db,journey=journey,
            tool_context=SimpleNamespace(workspace_id=student.workspace_id),possibility_id=row.id) is None
        db.add(ExecutionRun(workspace_id=student.workspace_id,requested_by='pai',task_type='path_explain',
            objective='Explore',status='completed',constraints={'possibility_id':row.id,'mirror_version':0}))
        db.commit()
        assert await request_research('program_search',student.workspace_id,db=db,journey=journey,
            tool_context=SimpleNamespace(workspace_id=student.workspace_id),possibility_id=row.id) is None
