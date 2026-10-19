"""Offline student-facing workspace, retirement and explicit roadmap handoff."""
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from app.models import ExecutionRun, Roadmap, StudentRecordRevision
from app.pai_c.memory import MemoryService
from app.pai_c.possibilities import PossibilityService
from app.routers.counselor_paths import prepare_roadmap
from app.routers.counselor_profile_cards import Review
from scripts.counselor_eval_support import StudentSession
from tests.test_profile_evidence import seed
from tests.test_counselor_deep_lean import research_journey


@pytest.mark.parametrize('kind', ['vault_fact', 'education'])
def test_remove_is_reconciled_idempotent_and_history_is_kept(kind):
    with StudentSession() as student, student.factory() as db:
        from app.memory.field_definitions import VaultFieldDefinitionService
        VaultFieldDefinitionService(db).upsert_definition({'key':'location.current_city',
            'category':'location','data_type':'string','validation_schema':{'type':'string'}})
        seed(db, student.workspace_id, kind)
        memory = MemoryService(db)
        card = next(c for c in memory.profile_cards(student.workspace_id) if c['kind'] == kind)
        request = Review(submission_id=uuid4(), action='remove', expected_digest=card['digest'])
        assert memory.review_profile_card(student.workspace_id, kind, card['id'], request)['saved']
        assert memory.review_profile_card(student.workspace_id, kind, card['id'], request)['saved']
        assert not any(c['id'] == card['id'] for c in memory.profile_cards(student.workspace_id))
        if kind == 'education':
            revisions = db.scalars(select(StudentRecordRevision).where(StudentRecordRevision.record_id == card['id'])).all()
            assert revisions[-1].after['status'] == 'retracted'
            assert revisions[-1].before['qualification_name'] == 'My qualification'


@pytest.mark.asyncio
async def test_new_roadmap_requires_explicit_current_program_check():
    from fastapi import HTTPException
    from app.models import Workspace
    from app.routers.counselor_paths import ProgramConsent
    with StudentSession() as student, student.factory() as db:
        journey = research_journey(student, db, confirmed=True)
        row = PossibilityService(db).add(student.workspace_id, journey.id, title='Practical design',
            why='My own evidence', kind='discovered', source='planner', status='exploring')
        workspace = db.get(Workspace, student.workspace_id)
        body = ProgramConsent(explore_places=True)
        with patch('app.routers.counselor_paths._authorized', return_value=workspace), patch('app.research.gateway.request_research', new_callable=AsyncMock) as gateway:
            with pytest.raises(HTTPException) as failure:
                await prepare_roadmap(row.id, body, student.workspace_id, db, None, None)
            assert failure.value.status_code == 409 and gateway.call_count == 0
            db.add(ExecutionRun(workspace_id=student.workspace_id, requested_by='pai', task_type='program_search',
                objective='Check', status='completed', constraints={'possibility_id':row.id,'mirror_version':1}))
            db.commit()
            gateway.return_value = {'ok':True,'data':{'run_id':'fake-run'}}
            await prepare_roadmap(row.id, body, student.workspace_id, db, None, None)
            await prepare_roadmap(row.id, body, student.workspace_id, db, None, None)
            assert len(db.scalars(select(Roadmap)).all()) == 1
            assert gateway.call_args.kwargs['trigger'] == 'student_route'
            assert gateway.call_args.kwargs['roadmap_id'] == row.roadmap_id


def test_workspace_projection_does_not_publish_private_map():
    from app.routers.counselor_workspace import counselor_workspace
    from app.models import Workspace
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        with patch('app.routers.counselor_workspace._authorized', return_value=workspace):
            result = counselor_workspace(student.workspace_id, db, None, None)
        text = str(result)
        for forbidden in ('private_notes', 'hypotheses', 'legacy_v1', 'legacy_v2', 'decision_difficulties'):
            assert forbidden not in text


def test_student_export_is_scoped_readonly_and_excludes_private_data():
    from app.pai_c.data_export import export_student_data
    from app.models import EventRecord, Workspace, CounselorNotebook, FileRecord
    import json
    with StudentSession() as student, student.factory() as db:
        db.add(Workspace(id='00000000-0000-0000-0000-000000000003',name='Other'))
        db.add(CounselorNotebook(workspace_id=student.workspace_id,version=1,last_event_id='early',notebook={'schema_version':3,'private_notes':'hidden interpretation'}))
        for id, wid, stamp, text in [('late',student.workspace_id,20,'Second'),('early',student.workspace_id,10,'First password=secret-value'),('foreign','00000000-0000-0000-0000-000000000003',1,'Other student')]:
            db.add(EventRecord(id=id,network_id=wid,type='workspace.message.posted',source='human:student',target='channel/pai',timestamp=stamp,payload={'content':text}))
        db.add(FileRecord(workspace_id=student.workspace_id,filename='record.pdf',size=10,storage_key='private-storage-key',uploaded_by='human:student'))
        db.commit()
        with patch.object(db,'commit',side_effect=AssertionError('read-only')):
            result=export_student_data(db,student.workspace_id)
        assert [row['id'] for row in result['conversation']]==['early','late']
        assert result['documents'][0]['filename']=='record.pdf'
        for forbidden in ['hidden interpretation','private_notes','secret-value','private-storage-key','Other student']:
            assert forbidden not in json.dumps(result)
        assert not db.new and not db.dirty and not db.deleted


def test_profile_sections_are_evidence_only_and_retirement_aware():
    from app.pai_c.understanding.views import profile_sections
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from tests.truth_map_fixtures import item
    data=CounselorNotebookData.model_validate({'schema_version':3,
        'said':[item(id='option',key='option.path',value='A direction'),item(id='old',key='myth.old',value='Retired',status='retired')],
        'self':[item(id='interest',key='interest.work',value='Making things'),item(id='value',key='value.security',value='Stability')],
        'private_notes':'Do not expose this'})
    result=profile_sections(data)
    assert [row['id'] for row in result['options']]==['option']
    assert result['interests'][0]['value']=='Making things'
    assert result['values'][0]['value']=='Stability'
    assert 'Do not expose' not in str(result) and 'Retired' not in str(result)
