"""Core R1: lossless World migration, evidence policies and read-only views."""
import importlib.util
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import select

from app.config import config
from app.models import CounselorNotebook, CounselorNotebookHistory
from app.pai_c.deep.migrate_v1 import migrate_v1
from app.pai_c.deep.migrate_v2 import migrate_v2
from app.pai_c.deep.notebook_schema import CounselorNotebookData, Item
from app.pai_c.deep.context import _trim_notebook, estimated_tokens, _json
from app.pai_c.deep.coverage import foundation_ready, enforce_mirror_readiness
from app.pai_c.memory import MemoryService
from app.pai_c.planner.patch import apply_patch, PatchRejected
from app.pai_c.planner.view import build_planner_view
from app.pai_c.understanding import views, data
from tests.test_counselor_notebook import notebook_db
from tests.truth_map_fixtures import item, STAMP

NOW = datetime.fromisoformat(STAMP)


def v2(people=True):
    value = migrate_v1({}, STAMP)
    if people:
        value["pressures"]["people"] = [{"role": "My guardian", "wish": "Stay nearby",
            "concern": "Losing daily support", "evidence": "Student described their guardian",
            "first_seen": STAMP, "last_confirmed": STAMP}]
    return value


def test_107_converts_latest_and_every_history_row_and_downgrades_exactly(notebook_db):
    db, workspace, _, events = notebook_db
    originals = [v2(), v2(False)]
    db.add(CounselorNotebook(workspace_id=workspace, notebook=originals[1], version=2, last_event_id=events[0]))
    for version, original in enumerate(originals, 1):
        db.add(CounselorNotebookHistory(workspace_id=workspace, notebook=original,
            version=version, source_event_id=events[0], created_at=NOW))
    db.commit()
    path = Path(__file__).parents[1] / "alembic/versions/107_truth_map_v3.py"
    spec = importlib.util.spec_from_file_location("migration107", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "106"
    with patch.object(migration, "op", Operations(MigrationContext.configure(db.connection()))):
        migration.upgrade()
        db.expire_all()
        latest = db.scalar(select(CounselorNotebook))
        history = db.scalars(select(CounselorNotebookHistory).order_by(CounselorNotebookHistory.version)).all()
        assert latest.notebook["schema_version"] == 3
        for row, original in zip(history, originals):
            assert row.notebook["legacy_v2"] == original
            parsed = CounselorNotebookData.model_validate(row.notebook)
            assert "people" not in parsed.pressures.model_dump()
            assert len(parsed.world.people) == len(original["pressures"]["people"])
        person = CounselorNotebookData.model_validate(history[0].notebook).world.people[0]
        assert (person.role, person.wish, person.worry) == ("My guardian", "Stay nearby", "Losing daily support")
        assert person.relation == "other" and person.influence == "unknown" and person.supportive is None
        migration.downgrade()
        db.expire_all()
        assert latest.notebook == originals[1]
        assert [row.notebook for row in history] == originals


def test_archive_private_immutable_preserved_on_write_and_export(notebook_db):
    db, workspace, _, events = notebook_db
    original = v2()
    original["private_notes"] = "Private archive sentinel"
    stored = migrate_v2(original)
    stored["private_notes"] = ""
    db.add(CounselorNotebook(workspace_id=workspace, notebook=stored, version=1, last_event_id=events[0]))
    db.commit()
    memory = MemoryService(db)
    notebook = memory.truth_map(workspace).notebook
    assert "legacy_v2" not in notebook.model_dump()
    assert "legacy_v2" not in CounselorNotebookData.analyst_schema()["properties"]
    for output in (_trim_notebook(notebook), build_planner_view(notebook).data,
                   memory.export_truth_map(workspace), memory.personal_view(workspace), memory.capability_view(workspace)):
        assert "Private archive sentinel" not in json.dumps(output, default=str)
    assert memory.export_truth_map(workspace)["latest"]["notebook"]["has_legacy_v2"] is True
    with pytest.raises(ValueError, match="read-only"):
        memory.apply_truth_map(workspace, {"legacy_v2": {}}, events[0])
    saved, _ = memory.apply_truth_map(workspace, notebook, events[0], expected_version=1)
    assert saved.notebook.legacy_v2 == original


@pytest.mark.parametrize("kind,level,allowed", [("said", None, False), ("said", "claimed", False),
    ("shown", "sustained", True), ("document", None, True), ("action", None, True), ("said", "proven", True)])
def test_demonstrated_requires_evidence_kind_or_level(kind, level, allowed):
    value = item(kind=kind, level=level, capability_status="demonstrated")
    if allowed:
        assert Item.model_validate(value).capability_status == "demonstrated"
    else:
        with pytest.raises(ValidationError):
            Item.model_validate(value)
        with pytest.raises(PatchRejected):
            apply_patch(CounselorNotebookData(), [{"op": "add", "part": "self", "item": {
                key: val for key, val in value.items() if key not in {"id", "first_seen", "last_confirmed"}}}], frozenset(), "")


def test_capability_policy_is_data_driven(tmp_path, monkeypatch):
    policy = data.load_policy()
    policy["demonstrated"]["kinds"] = []
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    with pytest.raises(ValidationError):
        Item.model_validate(item(kind="shown", capability_status="demonstrated"))


def populated():
    notebook = migrate_v2(v2())
    notebook.update(self=[item(key="interest.building"), item(key="value.autonomy", id="v"),
                          item(key="skill", id="s", capability_status="emerging")],
                    shown=[item(id="done", kind="shown", capability_status="demonstrated")],
                    sure={"score": 0, "asked_at": STAMP}, private_notes="PRIVATE")
    notebook["world"]["daily_life"] = [item(id="day")]
    notebook["world"]["education_story"] = [item(id="story")]
    notebook["world"]["social"] = [item(id="retired", status="retired")]
    return CounselorNotebookData.model_validate(notebook)


def test_areas_use_active_evidence_and_json_mapping_changes_result(tmp_path, monkeypatch):
    notebook = populated()
    snapshot = SimpleNamespace(facts={"identity.current_status": {"value": "In transition", "valid_from": STAMP}},
                               records={"education": [{"id": "education", "updated_at": STAMP}]})
    result = views.coverage_areas(notebook, snapshot)
    assert all(row["covered"] == (row["item_count"] >= row["min_items"]) for row in result.values())
    assert not result["family_social"]["covered"] and result["history"]["covered"]
    assert result["status"]["item_count"] == 2 and result["history"]["item_count"] == 3
    assert result["family_social"]["item_count"] == 1
    assert result["strengths"]["item_count"] == 2 and result["sure"]["last_confirmed"] == NOW
    (tmp_path / "areas.json").write_text(json.dumps({"changed": [{"path": "world.social"}]}))
    monkeypatch.setattr(views, "DATA_DIR", tmp_path)
    assert views.coverage_areas(notebook, snapshot) == {"changed": {"covered": False, "item_count": 0, "min_items": 1, "last_confirmed": None}}


def test_views_only_expose_approved_fields_and_do_not_mutate():
    notebook = populated()
    snapshot = SimpleNamespace(records={"education": [{"id": "edu"}], "test_attempt": [{"id": "test"}], "document": [{"id": "doc"}], "goal": [{"id": "excluded"}]})
    before = notebook.storage_data()
    academic, personal, capability = views.academic_view(notebook, snapshot), views.personal_view(notebook), views.capability_view(notebook)
    assert set(academic) == {"records", "education_story"}
    assert set(academic["records"]) == {"education", "test_attempt", "document"}
    assert set(personal) == {"world", "self", "source", "pressures", "sure"}
    assert all(row["capability_status"] is None for row in personal["self"])
    assert capability["demonstrated"][0]["id"] == "done"
    assert all(key in capability["emerging"][0] for key in ("evidence", "kind", "level"))
    for output in (academic, personal, capability):
        serialized = json.dumps(output)
        for key in ("tensions", "hypotheses", "identity_status", "decision_difficulties", "private_notes", "legacy_v1", "legacy_v2"):
            assert key not in serialized
    personal["world"]["people"].clear()
    assert notebook.storage_data() == before


@pytest.mark.parametrize("part", ["world.social", "world.daily_life", "world.responsibilities", "world.education_story"])
def test_world_items_add_update_confirm_retire(part):
    notebook = CounselorNotebookData()
    payload = {key: val for key, val in item().items() if key not in {"id", "first_seen", "last_confirmed"}}
    notebook = apply_patch(notebook, [{"op": "add", "part": part, "item": payload}], frozenset(), "", now=NOW)
    view = build_planner_view(notebook)
    identity = next(iter(view.ids))
    notebook = apply_patch(notebook, [{"op": "update", "id": identity, "fields": {"evidence": "More evidence", "capability_status": "emerging"}},
        {"op": "confirm", "id": identity, "evidence": "Confirmed"}, {"op": "retire", "id": identity, "reason": "Corrected"}], view.ids, "")
    row = data.at_path(notebook.model_dump(), part)[0]
    assert row["status"] == "retired" and row["capability_status"] == "emerging"
    assert not build_planner_view(notebook).ids


def test_people_visible_ids_trim_and_atomic_patch():
    notebook = CounselorNotebookData.model_validate(migrate_v2(v2()))
    person = notebook.world.people[0]
    for index in range(1, 12):
        notebook.world.people.append(person.model_copy(update={"id": str(index), "role": f"Role {index}", "last_confirmed": NOW + timedelta(days=index)}))
    view = build_planner_view(notebook, budget=1000)
    assert view.data["world"]["people"] and "11" in view.ids and person.id not in view.ids
    assert view.omitted["world.people"] > 0
    with pytest.raises(PatchRejected):
        apply_patch(notebook, [{"op": "upsert_person", "role": person.role, "evidence": "Hidden person"}], view.ids, "")
    updated = apply_patch(notebook, [{"op": "update", "id": "11", "fields": {"evidence": "New evidence", "worry": "New concern"}},
        {"op": "confirm", "id": "11", "evidence": "Confirmed"}, {"op": "retire", "id": "11", "reason": "Corrected"}], view.ids, "")
    assert updated.world.people[0] == person
    assert updated.world.people[-1].worry == "New concern" and updated.world.people[-1].status == "retired"


def test_migrated_family_visible_in_same_context_budget_and_retired_excluded(monkeypatch):
    monkeypatch.setattr(config, "PAI_COUNSELOR_NOTEBOOK_CONTEXT_TOKENS", 1800)
    original = v2()
    notebook = CounselorNotebookData.model_validate(migrate_v2(original))
    context = _trim_notebook(notebook)
    person = context["world"]["people"][0]
    previous = original["pressures"]["people"][0]
    assert (person["role"], person["wish"], person["worry"]) == (previous["role"], previous["wish"], previous["concern"])
    assert estimated_tokens(_json(context)) <= 1800
    assert list(context["world"]) == ["people", "daily_life", "social", "responsibilities", "education_story"]
    notebook.world.people[0].status = "retired"
    assert not _trim_notebook(notebook)["world"]["people"]


def test_readiness_foundation_and_prompt_guard_unchanged():
    notebook = populated()
    assert not foundation_ready(notebook) and not enforce_mirror_readiness(notebook).mirror_ready
    notebook.coverage.said = notebook.coverage.self = True
    assert foundation_ready(notebook)
    for key in type(notebook.coverage).model_fields:
        setattr(notebook.coverage, key, True)
    notebook.mirror_ready = True
    assert enforce_mirror_readiness(notebook).mirror_ready
    prompt = (Path(__file__).parents[1] / "app/pai_c/planner/prompts/planner.md").read_text()
    assert "Never invent a family member, occupation, wish or worry. Record only what the student said, in their words." in prompt


def test_voice_existing_private_interpretation_selection_unchanged():
    notebook = CounselorNotebookData(hypotheses=[{"text": "Tentative", "status": "open", "evidence_for": "Student evidence"}])
    assert _trim_notebook(notebook)["hypotheses"][0]["status"] == "open"
