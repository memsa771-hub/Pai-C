"""Application planning HTTP contract and workspace isolation."""
from datetime import datetime, timezone
from urllib.parse import parse_qsl

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (ApplicationPlan, ApplicationRequirement, ApplicationRoutine,
                        Channel, ChannelMember, DeadlineSettings, FileRecord, Institution,
                        KanbanTask, NotificationRecord, RoutineRecord, SavedInstitution,
                        StudentDeadline, User, Workflow, Workspace, WorkspaceMember)
from app.application_workspace import access as application_access
from app.deadlines.service import generate_due_notices


@compiles(JSONB, "sqlite")
def _compile_jsonb(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _setup(connection, record):
        connection.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [User, Workspace, WorkspaceMember, Channel, ChannelMember, FileRecord,
              KanbanTask, Workflow, RoutineRecord, Institution,
              SavedInstitution, ApplicationPlan, ApplicationRequirement, ApplicationRoutine,
              StudentDeadline, DeadlineSettings, NotificationRecord]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    session = Session(engine, autoflush=False)
    owner = User(email="student@example.test", display_name="Student")
    other_owner = User(email="other@example.test", display_name="Other Student")
    session.add_all([owner, other_owner])
    session.flush()
    first = Workspace(name="First", owner_user_id=owner.id, password_hash="first-secret")
    second = Workspace(name="Second", owner_user_id=other_owner.id, password_hash="second-secret")
    session.add_all([first, second])
    session.commit()
    # The auth boundary itself is covered separately; use an authenticated
    # student here so the route contract can be tested with SQLite.
    monkeypatch.setattr(application_access, "resolve_human", lambda *args: object())
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app), session, str(first.id), str(second.id)
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def _post(client, path, network, token="first-secret", **fields):
    return client.post(f"/v1/application-workspace/{path}",
                       headers={"X-Workspace-Token": token},
                       json={"network": network, **fields})


def _get(client, path, network, token="first-secret"):
    route, _, query = path.partition("?")
    return client.get(f"/v1/application-workspace/{route}",
                      headers={"X-Workspace-Token": token},
                      params={"network": network, **dict(parse_qsl(query))})


def test_student_can_add_search_and_save_private_institution(api):
    client, _, first, second = api
    created = _post(client, "institutions", first, name="Example University",
                    country_code="GB", website_url="https://example.edu").json()["data"]
    assert created["saved"] is True
    assert created["source"] == "student"
    assert _post(client, "institutions", first, name=" Example  University ",
                 country_code="gb").json()["data"]["id"] == created["id"]
    assert [row["id"] for row in _get(client, "institutions?q=Example", first).json()["data"]] == [created["id"]]
    assert _get(client, "institutions?q=Example", second, "second-secret").json()["data"] == []
    assert _post(client, f"saved/{created['id']}", second, "second-secret").status_code == 404


def test_application_and_requirements_are_scoped_and_not_submitted(api):
    client, _, first, second = api
    school = _post(client, "institutions", first, name="Example College", country_code="US").json()["data"]
    plan_response = _post(client, "applications", first, institution_id=school["id"],
                          program_name="Biology", intake="2027")
    assert plan_response.status_code == 200
    plan = plan_response.json()["data"]
    assert plan["status"] == "planning"
    assert plan["submitted_at"] is None
    assert _post(client, "applications", first, institution_id=school["id"],
                 program_name="Biology", intake="2027").status_code == 409
    requirement = _post(client, f"applications/{plan['id']}/requirements", first,
                        label="Academic transcript", kind="document",
                        source_url="https://example.edu/admissions").json()["data"]
    assert requirement["status"] == "todo"
    updated = client.patch(
        f"/v1/application-workspace/applications/{plan['id']}/requirements/{requirement['id']}",
        headers={"X-Workspace-Token": "first-secret"},
        json={"network": first, "status": "done"},
    )
    assert updated.json()["data"]["status"] == "done"
    assert len(_get(client, f"applications/{plan['id']}", first).json()["data"]["requirements"]) == 1
    assert _get(client, f"applications/{plan['id']}", second, "second-secret").status_code == 404


def test_application_task_workflow_and_calendar_share_ids(api):
    client, session, first, _ = api
    school = _post(client, "institutions", first, name="Example College", country_code="US").json()["data"]
    deadline = "2027-01-15T12:00:00Z"
    plan = _post(client, "applications", first, institution_id=school["id"],
                 deadline_at=deadline).json()["data"]
    item = _post(client, f"applications/{plan['id']}/requirements", first,
                 label="Portfolio", due_at="2027-01-10T12:00:00Z").json()["data"]
    workflow = Workflow(workspace_id=first, name="Review portfolio", description="",
                        steps=[{"id": "review", "name": "Review", "instruction": "Review portfolio",
                                "assignee": {"kind": "human", "human": "student"}}],
                        created_by="human:test")
    session.add(workflow)
    session.commit()
    linked = _post(client, f"applications/{plan['id']}/requirements/{item['id']}/task",
                   first, workflow_id=workflow.id)
    assert linked.status_code == 200, linked.text
    task_id = linked.json()["data"]["task_id"]
    assert linked.json()["data"]["workflow_id"] == workflow.id
    assert _post(client, f"applications/{plan['id']}/requirements/{item['id']}/task",
                 first, workflow_id=workflow.id).json()["data"]["task_id"] == task_id
    task = session.get(KanbanTask, task_id)
    task.status = "done"
    session.commit()
    detail = _get(client, f"applications/{plan['id']}", first).json()["data"]
    assert detail["requirements"][0]["status"] == "done"
    calendar = _get(client, "calendar?start=2027-01-01&end=2027-01-31", first).json()["data"]
    assert {event["type"] for event in calendar["events"]} == {"deadline", "requirement"}
    assert next(event for event in calendar["events"] if event["type"] == "requirement")["status"] == "done"
    assert _get(client, "calendar?start=2027-01-01&end=2027-01-31", first).status_code == 200


def test_routine_is_scoped_to_application_and_can_be_cancelled(api):
    client, session, first, second = api
    session.add(WorkspaceMember(workspace_id=first, agent_name="pai", status="online"))
    session.commit()
    school = _post(client, "institutions", first, name="Example College", country_code="US").json()["data"]
    plan = _post(client, "applications", first, institution_id=school["id"]).json()["data"]
    created = _post(client, f"applications/{plan['id']}/routines", first,
                    name="Weekly review", message="Check missing items with me",
                    hour=9, minute=0, days=[0], timezone="UTC")
    assert created.status_code == 200, created.text
    routine_id = created.json()["data"]["id"]
    assert _get(client, f"applications/{plan['id']}", first).json()["data"]["routines"][0]["id"] == routine_id
    assert client.delete(f"/v1/application-workspace/applications/{plan['id']}/routines/{routine_id}",
                         headers={"X-Workspace-Token": "second-secret"}, params={"network": second}).status_code == 404
    stopped = client.delete(f"/v1/application-workspace/applications/{plan['id']}/routines/{routine_id}",
                            headers={"X-Workspace-Token": "first-secret"}, params={"network": first})
    assert stopped.status_code == 200
    assert session.get(RoutineRecord, routine_id).status == "cancelled"


def test_mutations_require_student_identity(api, monkeypatch):
    client, _, first, _ = api
    monkeypatch.setattr(application_access, "resolve_human", lambda *args: None)
    result = _post(client, "institutions", first, name="Example University", country_code="CA")
    assert result.status_code == 403


def test_central_deadlines_and_idempotent_notifications(api):
    client, session, first, second = api
    school = _post(client, "institutions", first, name="Example College", country_code="US").json()["data"]
    plan = _post(client, "applications", first, institution_id=school["id"],
                 deadline_at="2027-01-15T12:00:00Z").json()["data"]
    created = client.post("/v1/deadlines", headers={"X-Workspace-Token": "first-secret"},
                          json={"network": first, "title": "Scholarship form", "due_on": "2027-01-15",
                                "category": "funding"})
    assert created.status_code == 200, created.text
    own_id = created.json()["data"]["source_id"]
    rows = client.get("/v1/deadlines", headers={"X-Workspace-Token": "first-secret"},
                      params={"network": first, "start": "2027-01-01", "end": "2027-01-31"}).json()["data"]["deadlines"]
    assert {row["source"] for row in rows} == {"personal", "application"}
    assert {row["application_id"] for row in rows if row["source"] == "application"} == {plan["id"]}
    assert client.get("/v1/deadlines", headers={"X-Workspace-Token": "second-secret"},
                      params={"network": second, "start": "2027-01-01", "end": "2027-01-31"}).json()["data"]["deadlines"] == []
    assert client.patch(f"/v1/deadlines/{own_id}", headers={"X-Workspace-Token": "second-secret"},
                        json={"network": second, "status": "done"}).status_code == 404
    assert generate_due_notices(session, first, now=datetime(2027, 1, 14, 12, tzinfo=timezone.utc)) == 2
    session.commit()
    assert generate_due_notices(session, first, now=datetime(2027, 1, 14, 12, tzinfo=timezone.utc)) == 0
    session.commit()
    assert session.query(NotificationRecord).filter_by(workspace_id=first, status="active").count() == 2
    updated = client.patch(f"/v1/deadlines/{own_id}", headers={"X-Workspace-Token": "first-secret"},
                           json={"network": first, "status": "done"})
    assert updated.status_code == 200
    assert session.query(NotificationRecord).filter_by(workspace_id=first, status="active").count() == 1


def test_deadline_reminder_settings_validate_timezone_and_can_pause(api):
    client, _, first, _ = api
    response = client.put("/v1/deadlines/settings/reminders",
                          headers={"X-Workspace-Token": "first-secret"},
                          json={"network": first, "timezone": "Asia/Karachi", "reminder_days": [1, 7, 1, -1]})
    assert response.status_code == 200
    assert response.json()["data"]["reminder_days"] == [7, 1, -1]
    invalid = client.put("/v1/deadlines/settings/reminders",
                         headers={"X-Workspace-Token": "first-secret"},
                         json={"network": first, "timezone": "Invalid/Zone", "reminder_days": [1]})
    assert invalid.status_code == 400
