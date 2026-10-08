"""Offline PR 2 contract tests for private Counselor Notebook storage."""

from uuid import uuid4
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.counseling.deep.notebook import (
    NotebookService, NotebookVersionConflict, NotebookWorkspaceNotFound,
)
from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.models import CounselorNotebook, CounselorNotebookHistory, EventRecord, User, Workspace
from app.routers.workspaces import delete_workspace


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid(type_, compiler, **kw):
    return "TEXT"


@pytest.fixture
def notebook_db():
    engine = create_engine("sqlite://", poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        User.__table__, Workspace.__table__, EventRecord.__table__,
        CounselorNotebook.__table__, CounselorNotebookHistory.__table__,
    ])
    with Session(engine) as db:
        first, second = str(uuid4()), str(uuid4())
        event_ids = (str(uuid4()), str(uuid4()))
        for workspace_id, event_id in zip((first, second), event_ids):
            db.add(Workspace(id=workspace_id, name="Student", status="active"))
            db.add(EventRecord(
                id=event_id, network_id=workspace_id, type="workspace.message.posted",
                source="human:student", target="channel/pai", timestamp=1,
            ))
        db.commit()
        yield db, first, second, event_ids
    engine.dispose()


def _note(**changes):
    return {"claims": [{
        "id": "c1", "claim": "Built a shop", "evidence_level": "tried",
        "evidence": "Student described a shop they built", "interest_source": "own_experience",
        "probed": True,
    }], **changes}


def test_notebook_schema_validation_rejects_unknown_fields_and_invalid_enums(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    with pytest.raises(ValidationError):
        service.apply(first, _note(unexpected="data"), events[0])
    with pytest.raises(ValidationError):
        service.apply(first, _note(depth_mode="automatic"), events[0])
    assert service.get(first).version == 0


def test_notebook_requires_evidence_and_student_source_event(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    missing = _note()
    missing["claims"][0]["evidence"] = " "
    with pytest.raises(ValidationError):
        service.apply(first, missing, events[0])
    with pytest.raises(ValueError, match="student event"):
        service.apply(first, _note(), events[1])
    assert service.get(first).version == 0


def test_notebook_strips_banned_content_and_keeps_coach_empty(notebook_db):
    db, first, _, events = notebook_db
    data = _note(
        emotional_notes="Anxiety after exams; political family tension",
        coach={"thirty_day_test": "secret"},
        engagement_style="short_answers", depth_mode="light", chapter="discovery",
        goal_history=[{"goal": "Study abroad", "source": "own_experience", "session": 1}],
    )
    data["claims"][0]["claim"] = "ADHD learner built a shop"
    saved = NotebookService(db).apply(first, data, events[0])
    assert saved.version == 1
    assert saved.notebook.coach == {}
    assert saved.notebook.engagement_style == "short_answers"
    assert saved.notebook.goal_history[0].goal == "Study abroad"
    assert "ADHD" not in saved.notebook.claims[0].claim
    assert "Anxiety" not in saved.notebook.emotional_notes
    assert "political" not in saved.notebook.emotional_notes


def test_banned_content_cannot_erase_required_evidence(notebook_db):
    db, first, _, events = notebook_db
    data = _note()
    data["claims"][0]["evidence"] = "ADHD"
    with pytest.raises(ValidationError):
        NotebookService(db).apply(first, data, events[0])


def test_concurrent_stale_apply_conflicts_then_refetch_retry_wins(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    a = service.get(first)
    b = service.get(first)
    assert service.apply(first, _note(), events[0], expected_version=a.version).version == 1
    with pytest.raises(NotebookVersionConflict):
        service.apply(first, _note(values=["independence"]), events[0], expected_version=b.version)
    latest = service.get(first)
    assert service.apply(first, _note(values=["independence"]), events[0], expected_version=latest.version).version == 2
    versions = db.scalars(select(CounselorNotebookHistory.version).where(
        CounselorNotebookHistory.workspace_id == first).order_by(CounselorNotebookHistory.version)).all()
    assert versions == [1, 2]


def test_notebook_workspace_isolation_and_deletion(notebook_db):
    db, first, second, events = notebook_db
    service = NotebookService(db)
    service.apply(first, _note(), events[0])
    assert service.get(second).version == 0
    with pytest.raises(ValueError, match="student event"):
        service.apply(second, _note(), events[0])
    with patch("app.routers.workspaces._verify_workspace_access", return_value=True):
        delete_workspace(first, db, x_workspace_token="test-token")
    assert db.get(Workspace, first).status == "deleted"
    with pytest.raises(NotebookWorkspaceNotFound):
        service.get(first)
    assert db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == first)) is None
    assert db.scalar(select(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == first)) is None


def test_physical_workspace_delete_cascades_notebook_and_history(notebook_db):
    db, first, _, events = notebook_db
    NotebookService(db).apply(first, _note(), events[0])
    db.execute(delete(Workspace).where(Workspace.id == first))
    db.commit()
    assert db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == first)) is None
    assert db.scalar(select(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == first)) is None
