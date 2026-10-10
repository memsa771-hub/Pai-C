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
    from tests.truth_map_fixtures import item
    return {"said": [item({"text": "Built a shop", "probed": True}, level="tried")], **changes}


def test_notebook_repairs_unknown_fields_and_invalid_enums(notebook_db):
    db, first, _, events = notebook_db
    snapshot, changes = NotebookService(db).apply(first, _note(unexpected="data", depth_mode="automatic"), events[0])
    assert snapshot.version == 1 and snapshot.notebook.depth_mode == "full"
    assert {(i.path, i.action) for i in changes} >= {("unexpected", "dropped_unknown_field"), ("depth_mode", "repaired")}


def test_notebook_requires_evidence_and_student_source_event(notebook_db):
    db, first, _, events = notebook_db
    missing = _note()
    missing["said"][0]["evidence"] = " "
    snapshot, changes = NotebookService(db).apply(first, missing, events[0])
    assert not snapshot.notebook.said
    assert any(i.path == "said[0]" and i.reason == "missing_evidence" for i in changes)
    with pytest.raises(ValueError, match="student event"):
        NotebookService(db).apply(first, _note(), events[1])


def test_notebook_validates_shape_without_content_classification(notebook_db):
    db, first, _, events = notebook_db
    data = _note(private_notes="Anxiety after exams; political family tension", engagement_style="short_answers", depth_mode="light", chapter="discovery", goal_history=[{"goal": "Study abroad", "source": "own_experience", "session": 1}])
    saved, _ = NotebookService(db).apply(first, data, events[0])
    assert saved.notebook.private_notes == data["private_notes"]
    assert saved.notebook.engagement_style == "short_answers"
    assert saved.notebook.goal_history[0].goal == "Study abroad"


@pytest.mark.parametrize("text", ["ADHD", "Political Science", "Religious Studies"])
def test_storage_preserves_valid_entry_text_without_word_matching(notebook_db, text):
    db, first, _, events = notebook_db
    data = _note()
    data["said"][0]["value"] = text
    snapshot, changes = NotebookService(db).apply(first, data, events[0])
    assert snapshot.notebook.said[0].value == text and changes == []


@pytest.mark.asyncio
async def test_fake_sensitive_checker_drops_changed_entry_and_keeps_academic_text(caplog):
    from tests.truth_map_fixtures import item
    previous, _ = sanitize_notebook({})
    candidate, _ = sanitize_notebook({"said": [item("Political Science"), item("family is PTI supporter", id="c2")]})
    checked = []
    async def checker(entries):
        checked.append(entries)
        return {entry["path"] for entry in entries if "PTI supporter" in entry["text"]}
    with caplog.at_level("INFO", logger="app.pai_c.deep.sensitive"):
        cleaned, removals = await filter_sensitive_changes(previous, candidate, checker)
    assert [i.id for i in cleaned.said] == ["c1"]
    assert [i.path for i in removals] == ["said[1]"]
    assert len(checked) == 1 and len(checked[0]) == 2
    assert "PTI supporter" not in caplog.text


@pytest.mark.asyncio
async def test_fake_checker_removes_changed_scalar_and_skips_unchanged_entries():
    previous, _ = sanitize_notebook(_note())
    candidate, _ = sanitize_notebook(_note(private_notes="I was diagnosed with ADHD."))
    checked = []
    async def checker(entries):
        checked.extend(entries)
        return {e["path"] for e in entries}
    cleaned, removals = await filter_sensitive_changes(previous, candidate, checker)
    assert cleaned.private_notes == "" and [i.path for i in removals] == ["private_notes"]
    assert checked == [{"path": "private_notes", "text": candidate.private_notes}]


@pytest.mark.asyncio
async def test_fake_checker_drops_sensitive_goal_item():
    from tests.truth_map_fixtures import item
    previous, _ = sanitize_notebook({})
    candidate, _ = sanitize_notebook({"said": [item("A personal affiliation", key="stated_goal")]})
    async def checker(entries):
        return {entry["path"] for entry in entries}
    cleaned, removals = await filter_sensitive_changes(previous, candidate, checker)
    assert not cleaned.said and [i.path for i in removals] == ["said[0]"]


@pytest.mark.asyncio
async def test_model_checker_uses_one_json_call_and_rejects_invalid_decision():
    with patch("app.pai_c.deep.sensitive.chat_completion", new=AsyncMock(return_value='{"decisions":[{"path":"self[0]","sensitive":false}]}')) as model:
        assert await model_sensitive_checker([{"path": "self[0]", "text": "An academic topic"}]) == set()
    assert model.await_count == 1
    with patch("app.pai_c.deep.sensitive.chat_completion", new=AsyncMock(return_value='{"decisions":[{"path":"self[0]","sensitive":"maybe"}]}')):
        with pytest.raises(ValueError, match="invalid path or decision"):
            await model_sensitive_checker([{"path": "self[0]", "text": "A statement"}])


def test_one_invalid_claim_does_not_block_five_valid_claims(notebook_db):
    db, first, _, events = notebook_db
    entries = [{**_note()["said"][0], "id": f"c{i}"} for i in range(1, 7)]
    entries[2]["evidence"] = ""
    snapshot, changes = NotebookService(db).apply(first, {"said": entries}, events[0])
    assert [i.id for i in snapshot.notebook.said] == ["c1", "c2", "c4", "c5", "c6"]
    assert any(i.path == "said[2]" and i.reason == "missing_evidence" for i in changes)


def test_unusable_top_level_or_empty_replacement_of_existing_notebook_rejected(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    with pytest.raises(ValueError, match="object"):
        service.apply(first, [], events[0])
    service.apply(first, _note(), events[0])
    with pytest.raises(ValueError, match="erase"):
        service.apply(first, {"said": [{"id": "c1", "key": "claim"}]}, events[0])
    assert len(service.get(first).notebook.said) == 1


def test_concurrent_stale_apply_conflicts_then_refetch_retry_wins(notebook_db):
    db, first, _, events = notebook_db
    service = NotebookService(db)
    a = service.get(first)
    service.apply(first, _note(), events[0], expected_version=a.version)
    with pytest.raises(NotebookVersionConflict):
        service.apply(first, _note(private_notes="updated"), events[0], expected_version=a.version)
    latest = service.get(first)
    assert service.apply(first, _note(private_notes="updated"), events[0], expected_version=latest.version)[0].version == 2
    assert db.scalars(select(CounselorNotebookHistory.version).where(CounselorNotebookHistory.workspace_id == first).order_by(CounselorNotebookHistory.version)).all() == [1, 2]


def test_notebook_workspace_isolation_and_deletion(notebook_db):
    db, first, second, events = notebook_db
    service = NotebookService(db)
    service.apply(first, _note(), events[0])
    assert service.get(second).version == 0
    with pytest.raises(ValueError, match="student event"):
        service.apply(second, _note(), events[0])
    with patch("app.routers.workspaces._verify_workspace_access", return_value=True):
        delete_workspace(first, db, x_workspace_token="test-token")
    with pytest.raises(NotebookWorkspaceNotFound):
        service.get(first)
    assert db.scalar(select(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == first)) is None


def test_physical_workspace_delete_cascades_notebook_and_history(notebook_db):
    db, first, _, events = notebook_db
    NotebookService(db).apply(first, _note(), events[0])
    db.execute(delete(Workspace).where(Workspace.id == first))
    db.commit()
    assert db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == first)) is None
    assert db.scalar(select(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == first)) is None
