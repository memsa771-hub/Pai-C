from fastapi.testclient import TestClient

from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import StudentJourney
from scripts.counselor_eval_support import StudentSession


def test_summary_api_shows_only_student_facing_summary_in_own_workspace():
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        row = db.get(StudentJourney, journey.id)
        row.counselor_summary_draft = {"status": "awaiting_confirmation", "version": 2,
                                       "reply": "Internal draft reply", "summary": {
                                           "stated_goal": {"value": "Study CS", "status": "answered"}}}
        db.commit()
        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            client = TestClient(app)
            params = {"network": student.workspace_id}
            assert client.get("/v1/counselor/summary", params=params).status_code == 401
            result = client.get("/v1/counselor/summary", params=params,
                                headers={"X-Workspace-Token": "synthetic-test-only"})
            assert result.status_code == 200
            assert result.json()["data"] == {"status": "awaiting_confirmation",
                                               "version": 2, "summary": {
                                                   "stated_goal": {"value": "Study CS", "status": "answered"}}}
        finally:
            app.dependency_overrides.pop(get_db, None)
