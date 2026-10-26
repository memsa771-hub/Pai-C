"""Offline student-facing workspace, retirement and student data export."""
from unittest.mock import patch
from scripts.counselor_eval_support import StudentSession


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


def test_workspace_projection_reports_the_server_stage():
    from app.routers.counselor_workspace import counselor_workspace
    from app.journey import JourneyService
    from app.models import Workspace
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        with patch('app.routers.counselor_workspace._authorized', return_value=workspace):
            result = counselor_workspace(student.workspace_id, db, None, None)
        assert result['data']['stage'] == journey.current_stage


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
        from app.models import RouteDecision
        db.add(RouteDecision(workspace_id=student.workspace_id,field_key='computer_science',title='Computer Science',
            verdict={'status':'open'},route={'needs':[]},steps=[{'key':'step_apply'}],steps_done=[True]))
        db.commit()
        with patch.object(db,'commit',side_effect=AssertionError('read-only')):
            result=export_student_data(db,student.workspace_id)
        assert 'roadmaps' not in result
        assert [(row['field_key'],row['steps_done']) for row in result['route_decisions']]==[('computer_science',[True])]
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
        'said':[item(id='option',key='option.path',value='A direction'),item(id='said-interest',key='interest.activity',value='A stated interest'),item(id='old',key='myth.old',value='Retired',status='retired')],
        'self':[item(id='interest',key='interest.work',value='Making things'),item(id='value',key='value.security',value='Stability')],
        'private_notes':'Do not expose this'})
    result=profile_sections(data)
    assert [row['id'] for row in result['options']]==['option']
    assert [row['value'] for row in result['interests']]==['A stated interest', 'Making things']
    assert result['values'][0]['value']=='Stability'
    assert 'Do not expose' not in str(result) and 'Retired' not in str(result)
