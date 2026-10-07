from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import config
from app.counseling.move import plan_move
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import StudentJourney
from scripts.counselor_eval_support import StudentSession


def test_internal_escalation_preserves_history_and_queues_replan():
    with StudentSession() as student, student.factory() as db:
        service = JourneyService(db)
        journey = service.ensure_counselor(student.workspace_id)
        for stage in ("FOUNDATION", "DIRECTION", "RESEARCHING", "ASSESSING", "PROPOSED", "CHOSEN"):
            journey = service.set_counselor_stage(student.workspace_id, journey.id, stage,
                                                  validated_choice=stage == "CHOSEN")
        db.commit()

        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            client = TestClient(app)
            body = {"workspace_id": student.workspace_id, "journey_id": journey.id,
                    "reason_type": "blocking_gap", "details": "Intake has closed"}
            with patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"):
                assert client.post("/v1/escalations", json=body).status_code == 401
                result = client.post("/v1/escalations", json=body,
                                     headers={"X-PAI-Service-Token": "local-test-token"})
                assert result.status_code == 200
            db.expire_all()
            row = db.get(StudentJourney, journey.id)
            assert row.current_stage == "DIRECTION"
            assert row.decisions[-1]["reason_type"] == "blocking_gap"
            assert row.next_recommended_action == {"type": "replan_discussion"}
            move = plan_move(stage="DIRECTION", requirements=[], states={},
                             snapshot=SimpleNamespace(), scope="in_scope",
                             student_question="", emotion="none", language="en",
                             replanning=True)
            assert move.type == "replan_discussion"
        finally:
            app.dependency_overrides.pop(get_db, None)
