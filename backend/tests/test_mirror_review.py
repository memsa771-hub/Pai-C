"""R3 correction gate and confirmation-bound feedback, entirely offline."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, inspect
from sqlalchemy.exc import IntegrityError

from app.models import (BackgroundJob, CounselorMirrorFeedback, CounselorNotebookHistory,
                        EventRecord, StudentJourney, StudentJourneyEvent, Workspace)
from app.journey import JourneyService
from app.pai_c.memory import MemoryService
from app.pai_c.policy.classifier import fallback_signals
from app.pai_c.policy.controller import decide, decision_context
from app.pai_c.policy.state import build_state
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.database import get_db
from app.main import app
from scripts.counselor_eval_support import StudentSession
from scripts.export_counselor_session import export_session
from tests.test_counselor_mirror import prepare, draft_ready, client_for
from tests.test_conversation_policy import state


def student_turn(student, db, *, edit=False):
    event = EventRecord(id=str(uuid4()), network_id=student.workspace_id,
        type="workspace.message.posted", source=f"human:{student.user_id}",
        target="channel/pai-counselor", payload={"content": "More student context."},
        metadata_={"mirror_edit_version": 1} if edit else {}, timestamp=student.next_timestamp())
    db.add(event)
    db.commit()
    return CounselorTurnInput(event.target, student.workspace_id, event.payload["content"], (), None,
                              event.id, event.timestamp, event.source)


def gate(db, turn):
    return build_state(db, turn, fallback_signals(), [])


def test_mirror_gate_stage_pending_and_edit_requires_two_messages_and_applied_patch():
    with StudentSession() as student, student.factory() as db:
        turn, journey, _ = prepare(student, db)
        assert gate(db, turn)["mirror_allowed"]
        row = db.get(StudentJourney, journey.id)
        row.current_stage = "MIRROR"
        db.commit()
        assert not gate(db, turn)["mirror_allowed"]
        row.current_stage = "DIRECTION"
        job = BackgroundJob(workspace_id=student.workspace_id, job_type="counselor.mirror", payload={})
        db.add(job)
        db.commit()
        for status in ("pending", "running"):
            job.status = status
            db.commit()
            assert not gate(db, turn)["mirror_allowed"]
        job.status = "succeeded"
        db.commit()
        edit = student_turn(student, db, edit=True)
        assert gate(db, edit)["mirror_correction"]
        assert not gate(db, edit)["mirror_allowed"]
        one = student_turn(student, db)
        assert not gate(db, one)["mirror_allowed"]
        two = student_turn(student, db)
        assert not gate(db, two)["mirror_allowed"]
        # A failed/rejected Planner has no accepted history and cannot unlock.
        assert not MemoryService(db).patch_applied_since(student.workspace_id, edit.source_event_id)
        db.add(CounselorNotebookHistory(workspace_id=student.workspace_id, version=2,
            notebook=MemoryService(db).truth_map(student.workspace_id).notebook.storage_data(),
            source_event_id=one.source_event_id))
        db.commit()
        assert gate(db, two)["mirror_allowed"]
        assert not gate(db, two)["mirror_correction"]
        assert decide({**gate(db, two), "summary_due": False}).action == "mirror"


@pytest.mark.parametrize("areas", [[], ["family_social", "history"]])
def test_correction_row_after_care_instruction_and_no_repeat_exemption(areas):
    signals = fallback_signals().model_copy(update={"mentioned_areas": areas})
    sample = state(mirror_correction=True, mirror_allowed=True, mentioned_areas=areas,
        intent="pushback", previous={"action": "explore_correction", "topic": areas[0] if areas else None})
    decision = decide(sample)
    assert (decision.rule_id, decision.action, decision.question_allowed, decision.invite) == (
        "mirror_changes", "explore_correction", True, False)
    assert decision.topic == (areas[0] if areas else None)
    instruction = decision_context(decision, signals, None)["instruction"]
    topic = " (about what their family wants them to study)" if areas else ""
    assert instruction.strip() == (
        "The student corrected your picture of them. Acknowledge it in a few words, without thanking or apologising at length. "
        "Reflect the correction in your own words so they know you understood what was wrong. "
        "Then ask one open question that helps you understand that part better" + topic +
        ". Do not repeat the old picture.")
    assert decide({**sample, "safety": {"level": "urgent"}}).action == "care"


@pytest.mark.parametrize("before", [None, 6])
def test_confirmation_proof_feedback_idempotency_and_historical_version(before):
    with StudentSession() as student, student.factory() as db:
        journey = draft_ready(student, db)
        row = db.get(StudentJourney, journey.id)
        if before is not None:
            row.counselor_summary_draft = {**row.counselor_summary_draft, "certainty_before": before}
        else:
            row.counselor_summary_draft = {k:v for k,v in row.counselor_summary_draft.items() if k != "certainty_before"}
        db.commit()
        client = client_for(student)
        base = "/v1/counselor/summary/"
        query = "?network=" + student.workspace_id
        headers = {"X-Workspace-Token": "synthetic-test-only"}
        body = {"version": 1, "understood": 4, "certainty_after": 8}
        try:
            assert client.post(base+"feedback"+query, json=body).status_code == 401
            denied = client.post(base+"feedback"+query, json=body, headers=headers)
            assert denied.status_code == 409 and denied.json()["detail"] == "This Mirror version cannot be rated"
            for _ in range(2):
                assert client.post(base+"confirm"+query, json={"version":1}, headers=headers).status_code == 200
            db.expire_all()
            proofs = db.scalars(select(StudentJourneyEvent).where(
                StudentJourneyEvent.event_type == "counselor.mirror.confirmed")).all()
            assert len(proofs) == 1
            assert proofs[0].payload == {"workspace_id": student.workspace_id, "mirror_version":1,
                "confirmed_at": proofs[0].payload["confirmed_at"], "certainty_before":before}
            assert datetime.fromisoformat(proofs[0].payload["confirmed_at"])
            notebook_before = MemoryService(db).truth_map(student.workspace_id)
            # Later draft changes must not invalidate an exact historical proof.
            row = db.get(StudentJourney, journey.id)
            row.counselor_summary_draft = {"type":"mirror", "version":2, "status":"awaiting_confirmation"}
            db.commit()
            assert client.post(base+"feedback"+query, json=body, headers=headers).status_code == 200
            repeated = client.post(base+"feedback"+query, json={**body,"understood":1}, headers=headers)
            assert repeated.status_code == 200 and repeated.json()["data"]["understood"] == 4
            assert client.post(base+"feedback"+query, json={**body,"version":2}, headers=headers).status_code == 409
            db.expire_all()
            ratings = db.scalars(select(CounselorMirrorFeedback)).all()
            assert len(ratings) == 1 and ratings[0].certainty_before == before
            assert MemoryService(db).truth_map(student.workspace_id).version == notebook_before.version
            exported = export_session(db, student.workspace_id)
            assert exported["mirror_feedback"][0]["mirror_version"] == 1
            assert exported["mirror_feedback"][0]["certainty_after"] == 8
            assert exported["mirror_confirmations"][0]["payload"]["certainty_before"] == before
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("body", [
    {"version":1,"understood":0}, {"version":1,"understood":6},
    {"version":1,"understood":True}, {"version":1,"understood":2.5},
    {"version":1,"understood":4,"certainty_after":-1},
    {"version":1,"understood":4,"certainty_after":11},
])
def test_feedback_ranges(body):
    with StudentSession() as student:
        client = client_for(student)
        try:
            response = client.post("/v1/counselor/summary/feedback?network="+student.workspace_id,
                json=body, headers={"X-Workspace-Token":"synthetic-test-only"})
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_feedback_cannot_access_other_workspace_and_old_status_is_not_proof():
    with StudentSession() as student, student.factory() as db:
        journey = draft_ready(student, db)
        row = db.get(StudentJourney, journey.id)
        row.counselor_summary_draft = {**row.counselor_summary_draft, "status":"confirmed"}
        foreign = Workspace(name="Other", password_hash="different-offline-token")
        db.add(foreign)
        db.commit()
        client = client_for(student)
        try:
            body = {"version":1,"understood":5}
            headers = {"X-Workspace-Token":"synthetic-test-only"}
            assert client.post("/v1/counselor/summary/feedback?network="+foreign.id,
                               json=body, headers=headers).status_code in (401,403)
            assert client.post("/v1/counselor/summary/feedback?network="+student.workspace_id,
                               json=body, headers=headers).status_code == 409
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_migration_110_roundtrip_constraints_and_cascade():
    path = Path(__file__).resolve().parents[1]/"alembic/versions/110_counselor_mirror_feedback.py"
    spec = importlib.util.spec_from_file_location("feedback_migration",path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "110" and migration.down_revision == "109"
    with StudentSession() as student:
        with student.engine.begin() as connection:
            CounselorMirrorFeedback.__table__.drop(connection)
            with patch.object(migration,"op",Operations(MigrationContext.configure(connection))):
                migration.upgrade()
            assert "pai_counselor_mirror_feedback" in inspect(connection).get_table_names()
        with student.factory() as db:
            db.add(CounselorMirrorFeedback(workspace_id=student.workspace_id,mirror_version=1,understood=5))
            db.commit()
            with pytest.raises(IntegrityError), db.begin_nested():
                db.add(CounselorMirrorFeedback(workspace_id=student.workspace_id,mirror_version=1,understood=4))
                db.flush()
            with pytest.raises(IntegrityError), db.begin_nested():
                db.add(CounselorMirrorFeedback(workspace_id=student.workspace_id,mirror_version=2,understood=6))
                db.flush()
            from sqlalchemy import delete
            db.execute(delete(Workspace).where(Workspace.id==student.workspace_id))
            db.commit()
            assert db.scalar(select(CounselorMirrorFeedback.id)) is None
        with student.engine.begin() as connection:
            with patch.object(migration,"op",Operations(MigrationContext.configure(connection))):
                migration.downgrade()
            assert "pai_counselor_mirror_feedback" not in inspect(connection).get_table_names()
