"""Offline entry-path and every exposed PAI C route's tenant boundary."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Base, get_db
from app.main import app
from app.models import AuthIdentity, PaiSession, User, Workspace, FileRecord, Roadmap
from app.security.identity import AuthenticatedIdentity
from scripts.counselor_eval_support import StudentSession


@contextmanager
def client_for(student):
    def database():
        with student.factory() as db:
            yield db
    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    with patch('app.database.SessionLocal', student.factory), patch('app.routers.events.SessionLocal', student.factory):
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)


def test_verified_identity_to_onboarding_refresh_logout_and_expiry():
    with StudentSession() as student:
        Base.metadata.create_all(student.engine, tables=[AuthIdentity.__table__, PaiSession.__table__])
        from tests.test_student_onboarding import FIELD_SPECS
        from app.memory.field_definitions import VaultFieldDefinitionService
        with student.factory() as db:
            fields = VaultFieldDefinitionService(db)
            for key, sensitivity, choices in FIELD_SPECS:
                schema = {'type': 'string'}
                if choices:
                    schema['enum'] = choices
                fields.upsert_definition(dict(key=key, category=key.split('.')[0], sensitivity=sensitivity,
                    data_type='string', validation_schema=schema,
                    conflict_policy='manual_review' if sensitivity == 'restricted' else 'latest_wins'))
            db.commit()
        identity = AuthenticatedIdentity('supabase', 'new-student', 'new@example.test', True)
        with student.factory() as db:
            # Use the real provisioning services; synthetic schema lacks only Channel.
            from app.models import Channel, ChannelMember
            Base.metadata.create_all(student.engine, tables=[Channel.__table__, ChannelMember.__table__])
        with client_for(student) as client, patch(
                'app.security.identity.SupabaseIdentityVerifier.verify', return_value=identity):
            login = client.post('/v1/auth/session', headers={
                'Authorization': 'Bearer fake-provider', 'X-PAI-Desktop': '1', 'Origin': 'pai://workspace'})
            assert login.status_code == 200
            data = login.json()['data']
            token = data['desktopToken']
            workspace_id = data['workspace']['workspaceId']
            auth = {'Authorization': 'Bearer ' + token}
            state = client.get('/v1/student-profile/onboarding', params={'network': workspace_id}, headers=auth)
            assert state.status_code == 200 and state.json()['data']['required']
            answers = dict(fullName='Test Student', preferredName='Student', statusCategory='student',
                nationality='Nationality', gender='undisclosed', dateOfBirth='2000-01-01',
                currentCountry='Country', currentCity='City')
            saved = client.post('/v1/student-profile/onboarding', params={'network': workspace_id},
                                headers=auth, json={'answers': answers})
            assert saved.status_code == 200
            assert saved.json()['data']['completed'], saved.json()
            with student.factory() as db:
                owner = db.scalar(select(User).where(User.email == identity.email))
                assert owner.onboarded_at is not None
                from app.memory.vault import VaultService
                assert VaultService(db).snapshot(workspace_id, include_sensitive=True)['identity.full_name'] == answers['fullName']
                from app.journey import JourneyService
                assert JourneyService(db).ensure_counselor(workspace_id).current_stage == 'IDENTITY'
            assert client.get('/v1/auth/session', headers=auth).status_code == 200
            refreshed = client.post('/v1/auth/session', headers={
                'Authorization': 'Bearer fake-provider-refresh', 'X-PAI-Desktop': '1',
                'X-PAI-Previous-Session': token, 'Origin': 'pai://workspace'})
            assert refreshed.status_code == 200
            assert refreshed.json()['data']['workspace']['workspaceId'] == workspace_id
            assert client.get('/v1/auth/session', headers=auth).status_code == 401
            auth = {'Authorization': 'Bearer ' + refreshed.json()['data']['desktopToken']}
            assert client.delete('/v1/auth/session', headers=auth).status_code == 200
            assert client.get('/v1/auth/session', headers=auth).status_code == 401
            assert client.get('/v1/auth/session', headers={'Authorization': 'Bearer pai_invalid'}).status_code == 401
            with student.factory() as db:
                from app.security.app_session import create_session, resolve_session
                owner = db.scalar(select(User).where(User.email == identity.email))
                expired = create_session(db, owner, provider='supabase')
                row, _ = resolve_session(db, expired)
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
            assert client.get('/v1/auth/session', headers={'Authorization': 'Bearer '+expired}).status_code == 401


def sample(schema, schemas):
    if '$ref' in schema:
        return sample(schemas[schema['$ref'].split('/')[-1]], schemas)
    if 'anyOf' in schema:
        return sample(next(s for s in schema['anyOf'] if s.get('type') != 'null'), schemas)
    if 'enum' in schema:
        return schema['enum'][0]
    kind = schema.get('type')
    if kind == 'object':
        return {key: sample(value, schemas) for key, value in schema.get('properties', {}).items()
                if key in schema.get('required', [])}
    if kind == 'array':
        return [sample(schema.get('items', {}), schemas)] * max(1, schema.get('minItems', 0))
    if kind in {'integer', 'number'}:
        return max(1, schema.get('minimum', 1))
    if kind == 'boolean':
        return True
    if schema.get('format') == 'date-time':
        return '2000-01-01T00:00:00Z'
    return 'x' * max(24, schema.get('minLength', 1))


SPEC = app.openapi()
PREFIXES = ('/v1/events', '/v1/counselor/', '/v1/roadmaps', '/v1/student-profile',
            '/v1/student-requests', '/v1/files')
CASES = [(path, method, spec) for path, methods in SPEC['paths'].items()
         if path.startswith(PREFIXES) for method, spec in methods.items()
         if method in {'get', 'post', 'patch', 'delete'}]


@pytest.mark.parametrize('path,method,spec', CASES, ids=[m.upper()+' '+p for p,m,_ in CASES])
@pytest.mark.parametrize('caller', ['anonymous', 'other_student'])
def test_all_pai_c_routes_reject_anonymous_and_other_workspace(path, method, spec, caller):
    with StudentSession() as student:
        Base.metadata.create_all(student.engine, tables=[PaiSession.__table__])
        with student.factory() as db:
            other = User(email='other@example.test', username='other', onboarded_at=datetime.now(timezone.utc))
            db.add(other)
            db.flush()
            foreign = Workspace(name='Other', owner_user_id=other.id, password_hash='other-machine')
            db.add(foreign)
            db.commit()
            foreign_id = str(foreign.id)
            from app.journey import JourneyService
            journey = JourneyService(db).ensure_counselor(foreign_id)
            foreign_file = str(uuid4())
            foreign_roadmap = str(uuid4())
            db.add(FileRecord(id=foreign_file, workspace_id=foreign_id, filename='private.txt',
                content_type='text/plain', size=1, storage_key='synthetic-only', uploaded_by='human:'+str(other.id)))
            db.add(Roadmap(id=foreign_roadmap, workspace_id=foreign_id, journey_id=journey.id,
                origin='stated_goal', title='Private roadmap', generation_status='ready'))
            db.commit()
            from app.security.app_session import create_session
            owner = db.get(User, student.user_id)
            token = create_session(db, owner, provider='supabase')
            db.commit()
        schemas = SPEC['components']['schemas']
        params = {'network': foreign_id}
        url = path
        for parameter in spec.get('parameters', []):
            name = parameter['name']
            if parameter['in'] == 'path':
                resource = foreign_file if name == 'file_id' else foreign_roadmap if name == 'roadmap_id' else str(uuid4())
                url = url.replace('{'+name+'}', resource)
            elif parameter['in'] == 'query' and parameter.get('required'):
                params[name] = foreign_id if name == 'network' else sample(parameter['schema'], schemas)
        options = {'params': params}
        content = spec.get('requestBody', {}).get('content', {})
        if 'application/json' in content:
            body = sample(content['application/json']['schema'], schemas)
            if isinstance(body, dict):
                body['network'] = foreign_id
                if path.startswith('/v1/files/trash'):
                    body['file_ids'] = [foreign_file]
                if 'url' in body:
                    body['url'] = 'https://example.test/fixture'
            options['json'] = body
        elif 'multipart/form-data' in content:
            options['data'] = {'network': foreign_id, 'path': 'fixture', 'filename': 'fixture.txt'}
            options['files'] = {'file': ('fixture.txt', b'offline', 'text/plain'), 'files': ('fixture.txt', b'offline', 'text/plain')}
        if caller == 'other_student':
            options['headers'] = {'Authorization': 'Bearer '+token}
        with client_for(student) as client:
            response = client.request(method, url, **options)
            assert response.status_code in {401, 403, 404}, (method, path, response.status_code, response.text)

def test_folder_noop_still_works_for_authenticated_owner():
    with StudentSession() as student:
        Base.metadata.create_all(student.engine, tables=[PaiSession.__table__])
        with student.factory() as db:
            from app.security.app_session import create_session
            token = create_session(db, db.get(User, student.user_id), provider='supabase')
            db.commit()
        with client_for(student) as client:
            result = client.patch('/v1/files/folders', headers={'Authorization': 'Bearer '+token},
                json={'network': student.workspace_id, 'path': 'folder', 'new_path': 'folder'})
            assert result.status_code == 200
            assert result.json()['data']['updated'] == 0


def test_pai_os_contract_names_and_service_token_rejection():
    from app.models import DecisionRecord, StudentRequest
    from app.config import config
    assert DecisionRecord.__tablename__ == 'pai_decision_records'
    assert StudentRequest.__tablename__ == 'pai_student_requests'
    with StudentSession() as student, client_for(student) as client, patch.object(config, 'PAI_OS_SERVICE_TOKEN', 'fake-service-only'):
        body = {'workspace_id': student.workspace_id, 'journey_id': str(uuid4()),
                'reason_type': 'blocking_gap', 'details': 'A blocker'}
        assert client.post('/v1/escalations', json=body).status_code == 401
        assert client.post('/v1/escalations', json=body,
                           headers={'X-PAI-Service-Token': 'incorrect'}).status_code == 401

def test_browser_cookie_session_refresh_and_logout():
    with StudentSession() as student:
        Base.metadata.create_all(student.engine, tables=[AuthIdentity.__table__, PaiSession.__table__])
        with student.factory() as db:
            owner = db.get(User, student.user_id)
            owner.supabase_uid = 'cookie-subject'
            identity = AuthenticatedIdentity('supabase', 'cookie-subject', owner.email, True)
            db.commit()
        with client_for(student) as client, patch('app.security.identity.SupabaseIdentityVerifier.verify', return_value=identity), patch('app.main.origins', ['https://student.example.test']), patch('app.main.allowed_origins', ['https://student.example.test']):
            origin = {'Origin': 'https://student.example.test'}
            login = client.post('/v1/auth/session', headers={**origin, 'Authorization': 'Bearer fake-cookie-provider'})
            assert login.status_code == 200
            assert 'desktopToken' not in login.json()['data']
            assert 'HttpOnly' in login.headers['set-cookie']
            assert 'SameSite=lax' in login.headers['set-cookie']
            assert client.get('/v1/auth/session').status_code == 200
            assert client.get('/v1/student-profile/onboarding', params={'network': student.workspace_id}).status_code == 200
            assert client.delete('/v1/auth/session', headers=origin).status_code == 200
            assert client.get('/v1/auth/session').status_code == 401
