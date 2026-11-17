"""Offline student-facing workspace, retirement and student data export."""
import pytest
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
            verdict={'status':'open'},route={'needs':[]},steps=[{'key':'step_apply'}],steps_done=[True],decision_version=1))
        db.commit()
        with patch.object(db,'commit',side_effect=AssertionError('read-only')):
            result=export_student_data(db,student.workspace_id)
        assert 'roadmaps' not in result
        assert 'mirrors' not in result and 'ratings' not in result
        assert set(result['mirror'])=={'header','unknowns','text','ready','version'}
        assert [(row['field_key'],row['steps_done']) for row in result['route_decisions']]==[('computer_science',[True])]
        assert [row['id'] for row in result['conversation']]==['early','late']
        assert result['documents'][0]['filename']=='record.pdf'
        for forbidden in ['hidden interpretation','private_notes','secret-value','private-storage-key','Other student']:
            assert forbidden not in json.dumps(result)
        assert not db.new and not db.dirty and not db.deleted


@pytest.mark.req("R-10")
def test_export_lists_the_choice_and_the_consent_with_the_guardian_email_but_no_token():
    from datetime import datetime, timezone
    from app.pai_c.data_export import export_student_data
    from app.models import GuardianConsent, RouteDecision
    import json
    stamp = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    with StudentSession() as student, student.factory() as db:
        row = RouteDecision(workspace_id=student.workspace_id, field_key='computer_science', title='Computer Science',
            verdict={'status': 'open'}, route={'needs': []}, steps=[], steps_done=[], decision_version=1,
            places=[{'programme_ref': 'p1', 'rank': 1}], intake={'term': 'autumn', 'year': 2027}, level='master',
            destination_country='DE', os_supported=True, authorized_at=stamp, guardian_required=True,
            guardian_authorized_at=stamp)
        db.add(row)
        db.flush()
        db.add(GuardianConsent(workspace_id=student.workspace_id, decision_id=row.id, decision_version=1,
            email='parent@example.test', token_hash='SECRETHASH', purpose='agree', outcome='agreed',
            text_version='v1', expires_at=stamp, used_at=stamp))
        db.commit()
        result = export_student_data(db, student.workspace_id)
        decision = result['route_decisions'][0]
        assert decision['places'] == [{'programme_ref': 'p1', 'rank': 1}]
        assert decision['intake'] == {'term': 'autumn', 'year': 2027}
        assert (decision['level'], decision['destination_country'], decision['os_supported'],
                decision['guardian_required']) == ('master', 'DE', True, True)
        assert decision['authorized_at'] and decision['guardian_authorized_at']
        consent, = result['guardian_consents']
        assert consent['email'] == 'parent@example.test'
        assert (consent['outcome'], consent['text_version'], consent['decision_version'],
                consent['purpose']) == ('agreed', 'v1', 1, 'agree')
        assert consent['created_at'] and consent['used_at'] and consent['expires_at']
        assert 'token_hash' not in consent and 'SECRETHASH' not in json.dumps(result, default=str)


@pytest.mark.req("R-10")
def test_erasing_the_workspace_removes_the_guardian_consent_rows():
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models import GuardianConsent, Workspace
    from app.routers.account import _erase_workspace
    from app.database import Base
    with StudentSession() as student, student.factory() as db:
        Base.metadata.create_all(student.engine)  # every table a deleted workspace cascades into
        db.add(GuardianConsent(workspace_id=student.workspace_id, decision_version=1, email='parent@example.test',
            token_hash='erase-hash', text_version='v1',
            expires_at=datetime(2026, 11, 8, tzinfo=timezone.utc)))
        db.commit()
        assert db.scalars(select(GuardianConsent)).all()
        _erase_workspace(db, db.get(Workspace, student.workspace_id))
        db.commit()
        assert db.scalars(select(GuardianConsent).where(
            GuardianConsent.workspace_id == student.workspace_id)).all() == []


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
