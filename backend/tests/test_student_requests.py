"""Student requests stay a PAI OS contract: existing questions are listed, asked
once and answered; the removed roadmap research no longer creates new ones."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.pai_c.student_requests import StudentRequestService
from app.database import get_db
from app.main import app
from app.models import ExecutionRun, StudentRequest
from scripts.counselor_eval_support import StudentSession


def _request(db, workspace_id, item_key, **fields):
    run = ExecutionRun(workspace_id=workspace_id, requested_by="openagents:pai", objective="Research",
                       task_type="program_search", status="needs_user_action",
                       created_at=datetime.now(timezone.utc))
    db.add(run)
    db.flush()
    row = StudentRequest(workspace_id=workspace_id, source="research", execution_run_id=run.id,
                         item_key=item_key, reason=fields.get("reason", "Need this detail"),
                         accepts_upload=fields.get("accepts_upload", False))
    db.add(row)
    db.flush()
    return run, row


def test_existing_request_is_asked_once_and_answered():
    with StudentSession() as student, student.factory() as db:
        run, _ = _request(db, student.workspace_id, "test_attempt[IELTS].overall_score", accepts_upload=True)
        service = StudentRequestService(db)
        requests = service.list(student.workspace_id)
        assert len(requests) == 1
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


def test_service_no_longer_syncs_research_runs():
    assert not hasattr(StudentRequestService, "sync_research_run")


def test_request_api_is_workspace_scoped():
    with StudentSession() as student, student.factory() as db:
        _request(db, student.workspace_id, "education.grade", reason="Need your result")
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
