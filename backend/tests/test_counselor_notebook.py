"""Offline PR 2 contract tests for private Counselor Notebook storage."""

from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.pai_c.deep.notebook import (
    NotebookService, NotebookVersionConflict, NotebookWorkspaceNotFound,
)
from app.pai_c.deep.notebook_sanitize import sanitize_notebook
from app.pai_c.deep.sensitive import filter_sensitive_changes, model_sensitive_checker
from app.models import CounselorNotebook, CounselorNotebookHistory, CounselorNotedQuestion, EventRecord, User, Workspace
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
        CounselorNotebook.__table__, CounselorNotebookHistory.__table__, CounselorNotedQuestion.__table__,
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


def test_notebook_repairs_unknown_fields_and_invalid_enums(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    snapshot, changes = service.apply(first, _note(unexpected="data", depth_mode="automatic"), events[0])
    assert snapshot.version == 1
    assert snapshot.notebook.depth_mode == "full"
    assert not hasattr(snapshot.notebook, "unexpected")
    assert {(issue.path, issue.action) for issue in changes} >= {
        ("unexpected", "dropped_unknown_field"), ("depth_mode", "repaired"),
    }


def test_notebook_requires_evidence_and_student_source_event(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    missing = _note()
    missing["claims"][0]["evidence"] = " "
    snapshot, changes = service.apply(first, missing, events[0])
    assert snapshot.notebook.claims == []
    assert any(issue.path == "claims[0]" and issue.reason == "missing_evidence" for issue in changes)
    with pytest.raises(ValueError, match="student event"):
        service.apply(first, _note(), events[1])
    assert service.get(first).version == 1


def test_notebook_validates_shape_without_content_classification(notebook_db):
    db, first, _, events = notebook_db
    data = _note(
        emotional_notes="Anxiety after exams; political family tension",
        coach={"thirty_day_test": "secret"},
        engagement_style="short_answers", depth_mode="light", chapter="discovery",
        goal_history=[{"goal": "Study abroad", "source": "own_experience", "session": 1}],
    )
    data["claims"][0]["claim"] = "ADHD learner built a shop"
    saved, changes = NotebookService(db).apply(first, data, events[0])
    assert saved.version == 1
    assert saved.notebook.coach == {}
    assert saved.notebook.engagement_style == "short_answers"
    assert saved.notebook.goal_history[0].goal == "Study abroad"
    assert saved.notebook.claims[0].claim == data["claims"][0]["claim"]
    assert saved.notebook.emotional_notes == data["emotional_notes"]
    assert not any(issue.path in {"claims[0]", "emotional_notes"} for issue in changes)


def test_storage_preserves_valid_entry_text_without_word_matching(notebook_db):
    db, first, _, events = notebook_db
    data = _note()
    data["claims"][0]["evidence"] = "ADHD"
    snapshot, changes = NotebookService(db).apply(first, data, events[0])
    assert snapshot.notebook.claims[0].evidence == data["claims"][0]["evidence"]
    assert changes == []


def test_academic_text_survives_storage_validation(notebook_db):
    db, first, _, events = notebook_db
    data = _note(
        person={"daily_life": "Studies Political Science and RELIGIOUS STUDIES. Reads Islamiat."},
        values=["politics and international relations", "comparative religion"],
    )
    data["claims"][0]["claim"] = "Studied political science"
    snapshot, changes = NotebookService(db).apply(first, data, events[0])
    assert snapshot.notebook.person.daily_life == data["person"]["daily_life"]
    assert snapshot.notebook.claims[0].claim == data["claims"][0]["claim"]
    assert snapshot.notebook.values == data["values"]
    assert changes == []


@pytest.mark.asyncio
async def test_fake_sensitive_checker_drops_changed_entry_and_keeps_academic_text(caplog):
    previous, _ = sanitize_notebook({})
    data = _note(person={"daily_life": "Studies Political Science and Religious Studies."})
    data["claims"].append({**data["claims"][0], "id": "c2", "claim": "family is PTI supporter"})
    candidate, _ = sanitize_notebook(data)
    checked = []

    async def fake_checker(entries):
        checked.append(entries)
        return {entry["path"] for entry in entries if "PTI supporter" in entry["text"]}

    with caplog.at_level("INFO", logger="app.pai_c.deep.sensitive"):
        cleaned, removals = await filter_sensitive_changes(previous, candidate, fake_checker)
    assert [claim.id for claim in cleaned.claims] == ["c1"]
    assert cleaned.person.daily_life == data["person"]["daily_life"]
    assert [item.path for item in removals] == ["claims[1]"]
    assert len(checked) == 1
    assert len(checked[0]) == 3
    assert "PTI supporter" not in caplog.text
    assert "claims[1]" in caplog.text


@pytest.mark.asyncio
async def test_fake_checker_removes_changed_scalar_and_skips_unchanged_entries():
    previous, _ = sanitize_notebook(_note())
    candidate, _ = sanitize_notebook(_note(emotional_notes="I was diagnosed with ADHD."))
    checked = []

    async def fake_checker(entries):
        checked.append(entries)
        return {entry["path"] for entry in entries}

    cleaned, removals = await filter_sensitive_changes(previous, candidate, fake_checker)
    assert cleaned.emotional_notes == ""
    assert [item.path for item in removals] == ["emotional_notes"]
    assert checked == [[{"path": "emotional_notes", "text": candidate.emotional_notes}]]


@pytest.mark.asyncio
async def test_fake_checker_drops_sensitive_optional_goal_as_one_changed_entry():
    previous, _ = sanitize_notebook({})
    candidate, _ = sanitize_notebook({
        "stated_goal": {"text": "A personal affiliation", "first_said_turn": 1},
    })

    async def fake_checker(entries):
        return {entry["path"] for entry in entries}

    cleaned, removals = await filter_sensitive_changes(previous, candidate, fake_checker)
    assert cleaned.stated_goal is None
    assert [item.path for item in removals] == ["stated_goal.text"]


@pytest.mark.asyncio
async def test_model_checker_uses_one_json_call_and_rejects_invalid_decision():
    with patch("app.pai_c.deep.sensitive.chat_completion",
               new=AsyncMock(return_value='{"decisions":[{"path":"values[0]","sensitive":false}]}')) as model:
        assert await model_sensitive_checker([{"path": "values[0]", "text": "A general academic topic"}]) == set()
    assert model.await_count == 1
    assert model.call_args.kwargs["response_format"] == {"type": "json_object"}
    with patch("app.pai_c.deep.sensitive.chat_completion",
               new=AsyncMock(return_value='{"decisions":[{"path":"values[0]","sensitive":"maybe"}]}')):
        with pytest.raises(ValueError, match="invalid path or decision"):
            await model_sensitive_checker([{"path": "values[0]", "text": "A statement"}])


def test_one_invalid_claim_does_not_block_five_valid_claims(notebook_db):
    db, first, _, events = notebook_db
    original = _note()["claims"][0]
    claims = [{**original, "id": f"c{index}"} for index in range(1, 7)]
    claims[2]["evidence"] = ""
    snapshot, changes = NotebookService(db).apply(first, {"claims": claims}, events[0])
    assert [claim.id for claim in snapshot.notebook.claims] == ["c1", "c2", "c4", "c5", "c6"]
    assert any(issue.path == "claims[2]" and issue.reason == "missing_evidence" for issue in changes)


def test_unusable_top_level_or_empty_replacement_of_existing_notebook_rejected(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    with pytest.raises(ValueError, match="object"):
        service.apply(first, ["not a notebook"], events[0])
    service.apply(first, _note(), events[0])
    with pytest.raises(ValueError, match="erase"):
        service.apply(first, {"claims": [{"id": "c1", "claim": "unsupported"}]}, events[0])
    assert len(service.get(first).notebook.claims) == 1


def test_concurrent_stale_apply_conflicts_then_refetch_retry_wins(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    a = service.get(first)
    b = service.get(first)
    assert service.apply(first, _note(), events[0], expected_version=a.version)[0].version == 1
    with pytest.raises(NotebookVersionConflict):
        service.apply(first, _note(values=["independence"]), events[0], expected_version=b.version)
    latest = service.get(first)
    assert service.apply(first, _note(values=["independence"]), events[0], expected_version=latest.version)[0].version == 2
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
