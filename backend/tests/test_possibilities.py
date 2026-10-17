"""Discover lifecycle and evidence gates; no external providers."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from sqlalchemy import select
from app.models import PaiPossibility, Roadmap, RoadmapStudentState, StudentJourney
from app.pai_c.possibilities import PossibilityService, PossibilityError
from app.pai_c.possibility_titles import valid_title
from app.pai_c.deep.mirror_schema import CounselorMirror, SavedCounselorMirror
from app.pai_c.planner.plan import validate_plan
from app.pai_c.planner.view import build_planner_view
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.policy.controller import decide, decision_context
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_mirror import mirror_data, prepare, client_for, draft_ready
from tests.test_conversation_policy import state
from tests.truth_map_fixtures import item


@pytest.mark.parametrize('title,expected', [('General study', True), ('Study', False),
    ('Study 2 routes', False), ('Study https://example.test', False),
    ('one two three four five six seven eight nine', False)])
def test_structural_title(title, expected):
    assert valid_title(title) is expected


def test_new_lane_title_evidence_required_old_read_accepted():
    data = mirror_data()
    CounselorMirror.model_validate(data)
    del data['roadmap_lanes'][0]['title']
    SavedCounselorMirror.model_validate(data)
    with pytest.raises(ValueError): CounselorMirror.model_validate(data)
    data = mirror_data()
    next(lane for lane in data['roadmap_lanes'] if lane['lane'] == 'strength_based')['evidence'] = []
    with pytest.raises(ValueError): CounselorMirror.model_validate(data)
    SavedCounselorMirror.model_validate(data)


@pytest.mark.parametrize('action', ['explore', 'save', 'dismiss'])
@pytest.mark.parametrize('status', ['suggested', 'saved', 'exploring', 'dismissed', 'chosen'])
def test_every_transition(action, status):
    expected = {'explore': {'suggested':'exploring','saved':'exploring','dismissed':'exploring','exploring':'exploring'},
        'save': {'suggested':'saved','dismissed':'saved','saved':'saved'},
        'dismiss': {'suggested':'dismissed','saved':'dismissed','exploring':'dismissed','dismissed':'dismissed'}}
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        service = PossibilityService(db)
        row = service.add(student.workspace_id, journey.id, title='Practical direction', why='Student evidence',
            kind='discovered', source='planner', status=status)
        if status not in expected[action]:
            with pytest.raises(PossibilityError): service.transition(student.workspace_id, row.id, action)
            assert row.status == status
        else:
            updated, changed = service.transition(student.workspace_id, row.id, action)
            assert updated.status == expected[action][status]
            assert changed is (status != expected[action][status])


def test_mirror_idempotency_dismissal_and_restore():
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        journey = db.get(StudentJourney, journey.id)
        journey.counselor_summary_draft = {'status':'confirmed','version':1,'mirror':mirror_data()}
        service = PossibilityService(db)
        pairs = service.from_mirror(journey)
        before = [deepcopy(service.serialize(row)) for _, row in pairs]
        assert [service.serialize(row) for _, row in service.from_mirror(journey)] == before
        lane, row = pairs[0]
        service.transition(student.workspace_id, row.id, 'dismiss')
        journey.counselor_summary_draft = {'status':'confirmed','version':2,'mirror':mirror_data()}
        assert service.from_mirror(journey)[0][1].status == 'dismissed'
        roadmap = Roadmap(workspace_id=student.workspace_id,journey_id=journey.id,title='Published direction',lane=lane['lane'],origin='stated_goal')
        db.add(roadmap); db.flush()
        db.add(RoadmapStudentState(roadmap_id=roadmap.id,journey_id=journey.id)); db.flush()
        service.link_lane(journey,lane,roadmap)
        assert db.scalar(select(RoadmapStudentState)).dismissed_at
        from app.pai_c.roadmaps.service import RoadmapService
        RoadmapService(db).dismiss(student.workspace_id,roadmap.id,False)
        assert row.status == 'exploring' and row.mirror_versions == [1,2]
        assert len(service.list(student.workspace_id)) == len(pairs)


def test_old_lane_title_fallback_and_collision(caplog):
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        journey = db.get(StudentJourney, journey.id)
        service = PossibilityService(db)
        lane = {'lane':'stated_goal','why':'An original direction','route':{'field':'Original field'}}
        assert service.lane_title(journey,lane) == 'Original field'
        lane['route'] = {}
        with patch('app.pai_c.possibilities.load_data',return_value={'stated_goal':'Edited label'}):
            assert service.lane_title(journey,lane) == 'Edited label'
        journey.counselor_summary_draft = {'status':'confirmed','version':1,'mirror':{'roadmap_lanes':[lane]}}
        row = service.from_mirror(journey)[0][1]
        other = service.add(student.workspace_id,journey.id,title='Published direction',why='Evidence',kind='discovered',source='planner',status='saved')
        roadmap=Roadmap(workspace_id=student.workspace_id,journey_id=journey.id,title=other.title,lane='stated_goal',origin='stated_goal')
        db.add(roadmap); db.flush()
        assert service.lane_title(journey,lane) == other.title
        old = row.title
        service.link_lane(journey,lane,roadmap)
        assert row.title == old and 'possibility_title_collision' in caplog.text
        assert row.id in caplog.text and other.id in caplog.text
        roadmap.title = 'Another published direction'
        service.link_lane(journey,lane,roadmap)
        assert row.title == roadmap.title


def test_planner_optional_validation_and_dismissed_title_not_readded():
    first, second = item('Built a project',kind='shown',id='first'), item('Enjoyed collaboration',id='second')
    notebook=CounselorNotebookData.model_validate({'shown':[first],'said':[second]})
    view=build_planner_view(notebook)
    raw={'next_move':'understand','intent':'Explore','target_gap':None,'give':'','avoid_questions':[],'playbooks':[],
        'possibility':{'title':'Collaborative practical work','why':'Evidence connects these','evidence_item_ids':[first['id'],second['id']]}}
    assert validate_plan(raw,view=view).possibility
    for ids in [[first['id']], [first['id'],'missing'], [second['id'],second['id']]]:
        invalid=deepcopy(raw); invalid['possibility']['evidence_item_ids']=ids
        assert validate_plan(invalid,view=view).possibility is None
    invalid=deepcopy(raw); invalid['possibility']['title']='Study 99'
    assert validate_plan(invalid,view=view).possibility is None
    with StudentSession() as student, student.factory() as db:
        _,journey,_=prepare(student,db); service=PossibilityService(db)
        row=service.add(student.workspace_id,journey.id,title='Practical work',why='Evidence',kind='discovered',source='planner',status='dismissed')
        again=service.add(student.workspace_id,journey.id,title=' PRACTICAL   work ',why='New explanation',kind='discovered',source='planner',status='suggested')
        assert again.id == row.id and again.status == 'dismissed'
        row.title='Inventedplace practical work'
        assert service.research_route(row)['place_preference'] == ''
        assert service.research_route(row)['field'] == row.title
        service.mark_mentioned(student.workspace_id,row.id); stamp=row.mentioned_at
        service.mark_mentioned(student.workspace_id,row.id); assert row.mentioned_at == stamp


@pytest.mark.parametrize('kind', ['discovered', 'student_added'])
@pytest.mark.parametrize('places,expected', [([], ''), (['Student place'], 'Student place'),
                                           (['First place', 'Second place'], '')])
def test_explore_route_uses_possibility_not_old_goal_or_evidence(kind, places, expected):
    from types import SimpleNamespace
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        service = PossibilityService(db)
        row = service.add(student.workspace_id, journey.id, title='Data engineering', why='Student evidence',
            kind=kind, source='planner' if kind == 'discovered' else 'student', status='suggested',
            evidence=[{'text':'An evidence quote that must never become the research field', 'item_id':None}])
        profile = SimpleNamespace(records={'goal':[{'details':{'field_of_study':'Computer science',
            'degree_level':'Student level', 'target_countries':places}}]})
        with patch('app.pai_c.memory.MemoryService.profile', return_value=profile):
            assert service.research_route(row) == {'field':'Data engineering', 'level':'Student level',
                'place_preference':expected, 'kind':''}


@pytest.mark.parametrize('lane_field,expected', [('Lane direction','Lane direction'), ('','Data engineering')])
def test_mirror_explore_route_uses_lane_field_then_title(lane_field, expected):
    from types import SimpleNamespace
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        journey = db.get(StudentJourney, journey.id)
        journey.counselor_summary_draft = {'mirror':{'roadmap_lanes':[
            {'lane':'strength_based','route':{'field':lane_field}}]}}
        service = PossibilityService(db)
        row = service.add(student.workspace_id, journey.id, title='Data engineering', why='Evidence',
            kind='strength_based', source='mirror', status='saved',
            evidence=[{'text':'Private evidence quote', 'item_id':None}])
        with patch('app.pai_c.memory.MemoryService.profile', return_value=SimpleNamespace(records={})):
            assert service.research_route(row) == {'field':expected, 'level':'', 'place_preference':'', 'kind':''}


def test_discover_policy_and_text():
    from types import SimpleNamespace
    inputs=state(); inputs.update(mirror_allowed=False,summary_due=False,discover_available=True,possibility_id='candidate',questions_in_last_two=False)
    result=decide(inputs)
    assert (result.action,result.topic,result.question_allowed,result.invite)==('discover','candidate',True,False)
    inputs['previous']=result.as_dict()
    assert decide(inputs)==result
    text=decision_context(result,None,None,SimpleNamespace(title='Practical work',why='Your project experience'))['instruction']
    assert 'Practical work' in text and 'Your project experience' in text
    inputs['questions_in_last_two']=True
    assert decide(inputs).action != 'discover'
    inputs.update(questions_in_last_two=False,discover_available=False)
    assert decide(inputs).action != 'discover'


def test_discover_spacing_from_confirmation_and_previous_discover():
    from uuid import uuid4
    from app.models import EventRecord, StudentJourneyEvent, CounselorTurnDecision
    from app.pai_c.policy.state import build_state
    from app.pai_c.policy.classifier import fallback_signals
    from app.pai_c.deep.turn_input import CounselorTurnInput
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        journey = db.get(StudentJourney, journey.id)
        journey.counselor_summary_draft = {'status':'confirmed','version':1,'mirror':mirror_data()}
        service=PossibilityService(db)
        service.add(student.workspace_id,journey.id,title='Practical direction',why='Evidence',kind='discovered',source='planner',status='suggested')
        stamp=student.next_timestamp()
        db.add(StudentJourneyEvent(workspace_id=student.workspace_id,journey_id=journey.id,
            event_type='counselor.mirror.confirmed',payload={'mirror_version':1},
            created_at=datetime.fromtimestamp(stamp/1000,timezone.utc)))
        for number in range(1,13):
            event=EventRecord(id=str(uuid4()),network_id=student.workspace_id,type='workspace.message.posted',
                source=f'human:{student.user_id}',target='channel/pai-counselor',payload={'content':'Student evidence'},timestamp=stamp+number)
            db.add(event); db.commit()
            turn=CounselorTurnInput(event.target,student.workspace_id,'Student evidence',(),None,event.id,event.timestamp,event.source)
            assert build_state(db,turn,fallback_signals(),[])['discover_available'] is (number in {6,12})
            if number == 6:
                db.add(CounselorTurnDecision(workspace_id=student.workspace_id,source_event_id=event.id,
                    source_timestamp=event.timestamp,move='none',decision={'action':'discover'})); db.commit()


def test_possibility_endpoints_auth_scope_and_explore_once():
    from unittest.mock import AsyncMock
    from app.main import app
    from app.models import StudentJourney, ExecutionRun
    with StudentSession() as student, student.factory() as db:
        journey=draft_ready(student,db)
        client=client_for(student); headers={'X-Workspace-Token':'synthetic-test-only'}
        try:
            assert client.post(f'/v1/counselor/summary/confirm?network={student.workspace_id}',json={'version':1},headers=headers).status_code==200
            db.expire_all(); journey=db.get(StudentJourney,journey.id)
            service=PossibilityService(db)
            row=service.add(student.workspace_id,journey.id,title='New practical field',why='Student evidence',kind='discovered',source='planner',status='suggested')
            run=ExecutionRun(workspace_id=student.workspace_id,requested_by='pai',task_type='roadmap_research',objective='Research',status='queued')
            db.add(run); db.commit()
            url=f'/v1/counselor/possibilities/{row.id}/explore?network={student.workspace_id}'
            assert client.get(f'/v1/counselor/possibilities?network={student.workspace_id}').status_code==401
            assert client.post(url).status_code==401
            with patch('app.research.gateway.request_research',AsyncMock(return_value={'ok':True,'data':{'run_id':run.id}})) as research:
                first=client.post(url,headers=headers)
                assert first.status_code==200,first.text
                assert client.post(url,headers=headers).status_code==200
                research.assert_awaited_once()
                assert research.call_args.kwargs['trigger']=='student_route'
            db.expire_all(); row=service.get(student.workspace_id,row.id)
            assert db.get(Roadmap,row.roadmap_id).origin=='operator_suggested'
            assert client.post(f'/v1/counselor/possibilities/{row.id}/save?network={student.workspace_id}',headers=headers).status_code==409
            assert client.post(f'/v1/counselor/possibilities/{row.id}/dismiss?network={student.workspace_id}',headers=headers).status_code==200
            assert client.post(f'/v1/counselor/possibilities/{row.id}/save?network={student.workspace_id}',headers=headers).status_code==200
            with pytest.raises(PossibilityError): service.get('00000000-0000-0000-0000-000000000000',row.id)
        finally: app.dependency_overrides.clear()


def test_migration_111_upgrade_constraints_and_downgrade():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from sqlalchemy.exc import IntegrityError
    spec=importlib.util.spec_from_file_location('migration111',Path(__file__).parents[1]/'alembic/versions/111_possibilities.py')
    migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.revision=='111' and migration.down_revision=='110'
    with StudentSession() as student:
        with student.engine.begin() as connection:
            PaiPossibility.__table__.drop(connection)
            with patch.object(migration,'op',Operations(MigrationContext.configure(connection))): migration.upgrade()
        with student.factory() as db:
            _,journey,_=prepare(student,db)
            row=PossibilityService(db).add(student.workspace_id,journey.id,title='Practical route',why='Evidence',kind='discovered',source='planner',status='suggested')
            db.commit()
            with pytest.raises(IntegrityError),db.begin_nested():
                db.add(PaiPossibility(workspace_id=student.workspace_id,journey_id=journey.id,title=row.title,normalized_title=row.normalized_title,why='Evidence',kind='discovered',source='planner',status='saved'))
                db.flush()
        with student.engine.begin() as connection:
            with patch.object(migration,'op',Operations(MigrationContext.configure(connection))): migration.downgrade()
            assert 'pai_possibilities' not in inspect(connection).get_table_names()


def test_choose_sets_possibility_chosen_and_preserves_decision_record():
    from tests.test_roadmaps import _journey, _card
    from app.pai_c.roadmaps.service import RoadmapService
    with StudentSession() as student, student.factory() as db:
        journey=_journey(db,student.workspace_id)
        roadmap=_card(db,student.workspace_id,journey.id,'Practical route')
        row=PossibilityService(db).add(student.workspace_id,journey.id,title=roadmap.title,why='Evidence',kind='discovered',source='planner',status='exploring',roadmap_id=roadmap.id)
        service=RoadmapService(db)
        service.list(student.workspace_id,presented=True)
        service.choose(student.workspace_id,roadmap.id,service.choice_token(roadmap,'test-secret'),'test-secret')
        assert row.status=='chosen'
        assert service.current_decision(student.workspace_id)['roadmap_id']==roadmap.id


@pytest.mark.asyncio
async def test_planner_stores_valid_possibility_once_with_plan_log():
    import json
    from unittest.mock import AsyncMock
    from app.models import CounselorNotebook, PaiTurnPlan
    from app.pai_c.deep.analysis import analyze_job
    from tests.test_counselor_deep_pr4 import _turn_job
    from scripts.eval.recorded_planner import PLAN
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        notebook=CounselorNotebookData.model_validate({'shown':[item('Built a project',kind='action',id='one')],
            'self':[item('Enjoyed helping',id='two')]})
        db.add(CounselorNotebook(workspace_id=student.workspace_id,version=1,notebook=notebook.storage_data(),last_event_id=event_id));db.commit()
        plan={**PLAN,'possibility':{'title':'Practical collaboration','why':'Two experiences connect','evidence_item_ids':['one','two']}}
        with patch('app.pai_c.deep.analysis.chat_completion',AsyncMock(return_value=json.dumps({'patch':[],'plan':plan}))):
            assert (await analyze_job(job,db))['status']=='applied'
            assert (await analyze_job(job,db))['status']=='duplicate'
        assert len(PossibilityService(db).list(student.workspace_id))==1
        assert db.scalar(select(PaiTurnPlan)).plan['possibility']['title']=='Practical collaboration'
