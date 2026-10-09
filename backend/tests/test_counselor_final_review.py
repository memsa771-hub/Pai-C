"""Final review regressions: student evidence, route queries and version budgets."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from app.config import config
from app.pai_c.deep.roadmaps import ground_roadmap
from app.plugins._shared.budget import bounded_research, spend
from app.pai_c.light_research import collect_light_research
from scripts.counselor_eval_support import StudentSession
from test_mirror_roadmaps import example


def grounded_case(label='unconfirmed'):
    mirror,cards=example()
    fact={'fact_id':'fact','quote':'Completed study is required','value':'Completed study',
          'label':label,'source_url':'https://official.example/route','checked_at':'2026-10-09',
          'decisive_field':'eligibility'}
    research={'lanes':[{'lane':mirror['roadmap_lanes'][0]['lane'],'facts':[fact]}],
              'decisive_fields':['eligibility']}
    return cards[0],mirror['roadmap_lanes'][0],{'fact':fact},research


def test_student_numbers_and_self_targets_need_no_research_citation():
    card,lane,facts,research=grounded_case()
    card.update(constraints_fit='You have 12 hours available',test_30_days='Build 3 projects in 30 days')
    result=ground_roadmap(card,lane,facts,research,{'notebook':{'constraints':'12 hours'}})
    assert result['generation_status']=='ready'
    assert result['constraints_fit']==card['constraints_fit']
    assert result['test_30_days']==card['test_30_days']
    assert result['sources'][0]['status']=='unconfirmed'


def test_outside_world_numbers_and_step_timing_require_research():
    card,lane,facts,research=grounded_case('verified')
    card.update(constraints_fit='It costs 9000',steps=[{'step':'Submit','when':'Next intake'}])
    result=ground_roadmap(card,lane,facts,research,{'notebook':{'hours':12}})
    assert result['constraints_fit']=='' and result['steps'][0]['when']==''
    assert {item['field'] for item in result['missing_facts']} >= {'constraints_fit','steps.0.when'}


def test_decisive_fact_must_be_cited_even_if_present():
    card,lane,facts,research=grounded_case()
    card['gap']=[]; card['citations']={}
    result=ground_roadmap(card,lane,facts,research)
    assert result['generation_status']=='needs_info'
    assert {'field':'eligibility','reason':'missing_decisive_fact'} in result['missing_facts']


@pytest.mark.asyncio
async def test_search_uses_route_and_goals_never_lane_why():
    capabilities=AsyncMock(return_value={'candidates':[]})
    brief={'mirror':{'roadmap_lanes':[{'lane':'stated_goal','why':'PRIVATE EXPLANATION',
      'route':{'field':'student field','level':'student level','place_preference':'student place','kind':'student kind'}}]},
      'goals':[{'title':'student objective'}]}
    await collect_light_research(SimpleNamespace(capabilities=capabilities),brief)
    search=capabilities.await_args.args[1]
    assert search['objective']=='student field student level student place student kind student objective'
    assert 'PRIVATE EXPLANATION' not in str(search)


def test_budget_resets_per_mirror_but_refresh_has_own_allowance():
    with StudentSession() as student, patch.object(config,'PAI_RESEARCH_MAX_CALLS_PER_STUDENT',1), \
         patch.object(config,'PAI_RESEARCH_REFRESH_MAX_CALLS',1):
        def attempt(version,scope='roadmap_light',key=None):
            with bounded_research(queries=5,fetches=5,seconds=30,workspace_id=student.workspace_id,
                 mirror_version=version,scope=scope,refresh_key=key):
                return spend('web.search')
        assert attempt(1) is None
        assert attempt(1)=='research_student_budget_exceeded'
        assert attempt(2) is None
        assert attempt(1)=='research_student_budget_exceeded'
        assert attempt(2,'stale_refresh','source') is None
        assert attempt(2,'stale_refresh','source')=='research_student_budget_exceeded'
        assert attempt(2,'stale_refresh','another-source')=='research_student_budget_exceeded'
        assert attempt(3,'stale_refresh','source') is None



def test_readiness_uses_cited_decisive_fields_not_model_status_or_unconfirmed_label():
    card,lane,facts,research=grounded_case()
    card['status']='needs_info'
    card['family_fit']=''
    result=ground_roadmap(card,lane,facts,research)
    assert result['generation_status']=='ready'
    assert result['sources'][0]['status']=='unconfirmed'
