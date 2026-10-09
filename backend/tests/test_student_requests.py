"""One durable question survives channels and resumes only from accepted facts."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.pai_c.student_requests import StudentRequestService
from app.database import get_db
from app.main import app
from app.models import ExecutionRun, NotificationRecord
from scripts.counselor_eval_support import StudentSession


def test_research_request_is_idempotent_and_asked_once():
    with StudentSession() as student, student.factory() as db:
        run = ExecutionRun(workspace_id=student.workspace_id,
                           requested_by="openagents:pai", objective="Research",
                           task_type="roadmap_research", status="needs_user_action",
                           pending_action={"type": "need_from_student", "items": [{
                               "field": "test_attempt[IELTS].overall_score",
                               "reason": "An English score affects this route",
                               "accepts_upload": True}]})
        db.add(run)
        db.flush()
        service = StudentRequestService(db)
        service.sync_research_run(run)
        service.sync_research_run(run)
        requests = service.list(student.workspace_id)
        assert len(requests) == 1
        assert db.query(NotificationRecord).filter_by(
            workspace_id=student.workspace_id,
            dedupe_key=f"research-request:{requests[0]['id']}").count() == 1
        assert requests[0]["accepts_upload"] is True
        assert requests[0]["item_key"] == "test_attempt[IELTS].overall_score"
        row = service.oldest_open(student.workspace_id)
        service.mark_asked(row)
        db.flush()
        assert service.serialize(row)["asked_at"] is not None
        service.mark_answered(student.workspace_id, run.id, row.item_key)
        db.flush()
        assert service.list(student.workspace_id) == []
        assert service.list(student.workspace_id, status="answered")[0]["answered_at"]


def test_request_api_is_workspace_scoped():
    with StudentSession() as student, student.factory() as db:
        run = ExecutionRun(workspace_id=student.workspace_id,
                           requested_by="openagents:pai", objective="Research",
                           task_type="roadmap_research", status="needs_user_action",
                           created_at=datetime.now(timezone.utc),
                           pending_action={"type": "need_from_student", "items": [{
                               "field": "education.grade", "reason": "Need your result"}]})
        db.add(run)
        db.flush()
        StudentRequestService(db).sync_research_run(run)
        db.commit()
        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            client = TestClient(app)
            params = {"network": student.workspace_id}
            assert client.get("/v1/student-requests", params=params).status_code == 401
            response = client.get("/v1/student-requests", params=params,
                                  headers={"X-Workspace-Token": "synthetic-test-only"})
            assert response.status_code == 200
            assert response.json()["data"]["requests"][0]["item_key"] == "education.grade"
        finally:
            app.dependency_overrides.pop(get_db, None)
