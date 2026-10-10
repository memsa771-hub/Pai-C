"""P2a offline migration, ownership, archive and Vault boundary regression tests."""
import ast
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import select

from app.pai_c.deep.migrate_v1 import migrate_v1, MISSING_EVIDENCE
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.deep.notebook_sanitize import sanitize_notebook
from app.pai_c.deep.coverage import foundation_ready
from app.pai_c.deep.context import _trim_notebook
from app.pai_c.deep.sensitive import filter_sensitive_changes
from app.pai_c.memory import MemoryService
from app.models import CounselorNotebook, CounselorNotebookHistory
from tests.test_counselor_notebook import notebook_db
from tests.truth_map_fixtures import STAMP, item


def legacy():
    return {"stated_goal": {"text": "Build things", "source_of_goal": "reels", "first_said_turn": 2},
        "person": {"current_situation": "In transition", "daily_life": "Helping at home", "location_context": "Prefer to remain close"},
        "claims": [{"id": "old", "claim": "Built independently", "evidence_level": "proven", "evidence": "I built it", "interest_source": "own_experience", "probed": True}],
        "strengths": [{"trait": "Persistence", "evidence": "Kept trying", "confidence": "high"}],
        "growth_areas": [{"trait": "Practice", "evidence": "I need practice", "confidence": "medium"}],
        "drivers": [{"driver": "Independence", "weight": "strong", "evidence": "I want independence"}],
        "values": ["Autonomy"], "family": {"father": {"wish": "Security", "underlying_concern": "Stability"}, "mother": {"wish": "Stay nearby", "underlying_concern": "Support"}, "others": "Try options", "pressure_level": "Strong"},
        "constraints": [{"type": "time", "detail": "Evenings only", "hard": True}],
        "learning_style": "Practice", "work_preferences": "Hands on", "emotional_notes": "Unsure",
        "hypotheses": [{"text": "Likes independent work", "status": "open", "evidence_for": "Built it", "evidence_against": ""}],
        "open_questions": [{"priority": 1, "area": "certainty", "question_intent": "Explore confidence"}],
        "coverage": {"person": True, "education": True}, "mirror_ready": True, "mirror_blockers": [],
        "engagement_style": "open", "depth_mode": "full", "chapter": "discovery",
        "goal_history": [{"goal": "Build things", "source": "reels", "session": 1}], "coach": {}, "unknown_future_field": {"raw": "Retained exactly"}}


def test_migration_preserves_all_original_fields_and_approved_mappings():
    original = legacy()
    migrated = migrate_v1(original, STAMP, "2026-02-01T00:00:00+00:00")
    assert migrated["legacy_v1"] == original
    assert original == legacy()
    notebook = CounselorNotebookData.model_validate(migrated)
    assert notebook.schema_version == 2
    assert notebook.shown[0].value == {"text": "Built independently", "probed": True}
    assert next(i for i in notebook.self if i.key == "driver").value["weight"] == "strong"
    assert next(i for i in notebook.self if i.key == "strength").confidence == "high"
    assert next(i for i in notebook.self if i.key == "limit").value["hard"] is True
    assert [i.category for i in notebook.source] == ["media", "self"]
    assert [p.role for p in notebook.pressures.people] == ["father", "mother", "other"]
    assert notebook.private_notes == "Unsure" and not notebook.mirror_ready
    assert next(i for i in notebook.said if i.key == "daily_life").evidence == MISSING_EVIDENCE
    assert next(i for i in notebook.said if i.key == "daily_life").confidence == "low"
    assert all(i.vault_fact_ref is None for i in notebook.said)
    assert migrate_v1(migrated, STAMP) == migrated


def test_actual_migration_updates_latest_and_each_history_version(notebook_db):
    db, workspace, _, events = notebook_db
    original = legacy()
    db.add(CounselorNotebook(workspace_id=workspace, notebook=original, version=2, updated_at=STAMP, last_event_id=events[0]))
    # SQLAlchemy datetime columns require datetime objects.
    from datetime import datetime
    row = next(x for x in db.new if isinstance(x, CounselorNotebook))
    row.updated_at = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    for version, timestamp in ((1, STAMP), (2, "2026-02-01T00:00:00+00:00")):
        db.add(CounselorNotebookHistory(workspace_id=workspace, notebook=original, version=version, source_event_id=events[0], created_at=datetime.fromisoformat(timestamp)))
    db.commit()
    path = Path(__file__).parents[1] / "alembic/versions/101_truth_map_v2.py"
    spec = importlib.util.spec_from_file_location("truth_map_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with patch.object(migration, "op", Operations(MigrationContext.configure(db.connection()))):
        migration.upgrade()
    db.expire_all()
    latest = db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace))
    history = db.scalars(select(CounselorNotebookHistory).order_by(CounselorNotebookHistory.version)).all()
    assert latest.notebook["legacy_v1"] == original
    assert latest.notebook["said"][0]["first_seen"].startswith("2026-01-01")
    assert latest.notebook["said"][0]["last_confirmed"].startswith("2026-03-01")
    assert history[1].notebook["said"][0]["first_seen"].startswith("2026-02-01")
    assert all(h.notebook["legacy_v1"] == original for h in history)


@pytest.mark.parametrize("data", [{"schema_version": 1}, {"person": {}}, {"claims": []}])
def test_v1_rejected_after_migration(data):
    with pytest.raises((ValueError, ValidationError)):
        sanitize_notebook(data)


def test_new_items_need_evidence_and_objective_references():
    clean, issues = sanitize_notebook({"said": [item(evidence=""), item(key="education"), item(key="education", vault_fact_ref="record-id", value="Student sees this as a foundation")]})
    assert len(clean.said) == 1 and clean.said[0].vault_fact_ref == "record-id"
    assert len(issues) == 2


def test_foundation_gate_uses_said_and_self_only():
    assert foundation_ready(CounselorNotebookData(coverage={"said": True, "self": True}))
    assert not foundation_ready(CounselorNotebookData(coverage={"said": True}))


def test_archive_is_read_only_and_never_in_context_schema_export(notebook_db):
    db, workspace, _, events = notebook_db
    original = legacy()
    db.add(CounselorNotebook(workspace_id=workspace, notebook=migrate_v1(original, STAMP), version=1, last_event_id=events[0]))
    db.commit()
    service = MemoryService(db)
    previous = service.truth_map(workspace)
    assert "legacy_v1" not in previous.notebook.model_dump()
    assert "legacy_v1" not in json.dumps(CounselorNotebookData.analyst_schema())
    assert "unknown_future_field" not in json.dumps(_trim_notebook(previous.notebook))
    summary = service.understanding_summary(workspace)
    assert set(summary) == {"said", "source", "pressures", "self", "sure"}
    assert "legacy_v1" not in summary and "private_notes" not in summary
    from scripts.export_counselor_session import export_session
    # The full exporter uses additional tables; facade output is the identical notebook block.
    exported = service.export_truth_map(workspace)
    assert exported["latest"]["notebook"]["has_legacy_v1"] is True
    assert "unknown_future_field" not in json.dumps(exported, default=str)
    with pytest.raises(ValueError, match="read-only"):
        service.apply_truth_map(workspace, {"legacy_v1": {}}, events[0])
    snapshot, _ = service.apply_truth_map(workspace, previous.notebook, events[0], expected_version=1)
    assert snapshot.notebook.legacy_v1 == original
    assert db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace)).notebook["legacy_v1"] == original


@pytest.mark.asyncio
async def test_sensitive_batch_never_receives_archive():
    notebook = CounselorNotebookData.model_validate(migrate_v1(legacy(), STAMP))
    checked = []
    async def checker(entries):
        checked.extend(entries)
        return set()
    await filter_sensitive_changes(CounselorNotebookData(), notebook, checker)
    assert "unknown_future_field" not in json.dumps(checked)
    assert all(not e["path"].startswith("legacy_v1") for e in checked)


def test_certainty_history_survives_omitted_history(notebook_db):
    db, workspace, _, events = notebook_db
    service = MemoryService(db)
    first, _ = service.apply_truth_map(workspace, {"sure": {"score": 3, "reason": "Still exploring", "asked_at": STAMP}}, events[0])
    second, _ = service.apply_truth_map(workspace, {"sure": {"score": 7, "reason": "More evidence", "asked_at": STAMP}}, events[0], expected_version=first.version)
    third, _ = service.apply_truth_map(workspace, {"sure": {"score": 8, "reason": "Test completed", "asked_at": STAMP}}, events[0], expected_version=second.version)
    assert [r.score for r in third.notebook.sure.history] == [3, 7]


def test_notebook_access_outside_pai_c_only_uses_memory_facade():
    app = Path(__file__).parents[1] / "app"
    for path in app.rglob("*.py"):
        if "pai_c" in path.relative_to(app).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.pai_c.deep.notebook", str(path)
                assert all(alias.name != "NotebookService" for alias in node.names), str(path)


def test_vault_extractor_stops_interpretation_but_preserves_objective_targets():
    from types import SimpleNamespace
    from app.memory.extractor import _validate, _extractor_specs, build_user_prompt, SYSTEM_PROMPT
    text = "I want to study further and be independent"
    turn = SimpleNamespace(user_text=text, user_event_id="event", records={}, vault={}, existing_memories=[], recent=[], assistant_text="")
    base = {"candidate_type": "student_record", "quote": text, "confidence": 0.9, "attribution": {"claim_owner": "student"}}
    for kind in ("student_voice_statement", "external_influence"):
        assert _validate({**base, "key": kind, "proposed_value": {"statement": text}}, turn, set()) is None
    assert _validate({**base, "candidate_type": "vault_fact", "key": "career.primary_interest", "proposed_value": "Study"}, turn, {"career.primary_interest"}) is None
    details = {"stated_preference": "Study further", "degree_level": "Next level", "target_countries": ["Student preference"], "field_of_study": "Student choice", "target_intake": "Later", "underlying_objective": "Independence", "drivers": ["career"], "constraints": ["Stay nearby"], "career_direction": "Research"}
    candidate = _validate({**base, "key": "goal", "proposed_value": {"goal_type": "education", "title": "Study further", "details": details}}, turn, set())
    assert candidate is not None
    assert set(candidate.proposed_value["details"]) == {"stated_preference", "degree_level", "target_countries", "field_of_study", "target_intake"}
    specs = _extractor_specs()
    assert "student_voice_statement" not in specs and "external_influence" not in specs
    assert set(specs["goal"]["properties"]["details"]["properties"]) == set(candidate.proposed_value["details"])
    prompt = build_user_prompt(turn, [{"key": "career.primary_interest"}, {"key": "identity.preferred_name"}])
    assert "career.primary_interest" not in prompt
    assert "identity.preferred_name" in prompt
    assert "Truth Map" in SYSTEM_PROMPT


def test_research_brief_uses_public_truth_map_summary():
    from types import SimpleNamespace
    from app.research.gateway import _research_brief
    from scripts.counselor_eval_support import StudentSession
    with StudentSession() as student, student.factory() as db:
        summary = {"said": [item("Student goal", key="stated_goal", status="active")], "source": [], "pressures": {"items": [], "people": []}, "self": [], "sure": {"score": None}}
        snapshot = SimpleNamespace(facts={}, records={})
        journey = SimpleNamespace(counselor_summary_draft={"mirror": {}, "version": 1})
        with patch.object(MemoryService, "understanding_summary", return_value=summary) as reader:
            brief = _research_brief(db, student.workspace_id, journey, snapshot)
        reader.assert_called_once_with(student.workspace_id)
        assert brief["notebook"] == summary and brief["stated_preference"] == "Student goal"
        assert "private_notes" not in brief["notebook"]


@pytest.mark.parametrize("number,name", [(2, "analyst"), (3, "mirror"), (4, "roadmap_builder"), (6, "sensitive_check")])
def test_v2_documented_prompts_match_runtime(number, name):
    backend = Path(__file__).parents[1]
    docs = backend.parent / "docs/counselor/COUNSELOR_V3_PROMPTS.md"
    if not docs.exists():
        docs = Path("/docs/counselor/COUNSELOR_V3_PROMPTS.md")
    section = docs.read_text(encoding="utf-8").split(f"## {number}.", 1)[1].split("\n## ", 1)[0]
    documented = section.split("```text\n", 1)[1].split("\n```", 1)[0]
    assert documented.rstrip() == (backend / f"app/pai_c/deep/prompts/{name}.md").read_text(encoding="utf-8").rstrip()


@pytest.mark.asyncio
async def test_analyst_outputs_v2_and_drops_objective_item_without_reference():
    from unittest.mock import AsyncMock
    from scripts.counselor_eval_support import StudentSession
    from tests.test_counselor_deep_pr4 import _turn_job
    from app.pai_c.deep.analysis import analyze_job
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        candidate = {"schema_version": 2, "said": [item("A student wish"), item("An objective copy", key="education", id="bad")]}
        with patch("app.pai_c.deep.analysis.chat_completion", AsyncMock(return_value=json.dumps({"notebook": candidate}))) as model:
            result = await analyze_job(job, db)
        saved = MemoryService(db).truth_map(student.workspace_id).notebook
        assert saved.schema_version == 2 and len(saved.said) == 1
        assert result["sanitized"] >= 1
        assert "legacy_v1" not in model.call_args.kwargs["messages"][0]["content"]


def test_snapshot_ids_are_available_for_vault_references():
    from types import SimpleNamespace
    from app.pai_c.deep.context import _profile
    db = SimpleNamespace(get=lambda *args: None)
    snapshot = SimpleNamespace(facts={"objective.fact": {"id": "fact-id", "value": "Fact", "source_type": "document"}}, records={}, issues=[])
    with patch.object(MemoryService, "profile", return_value=snapshot):
        assert _profile(db, "workspace")["facts"]["objective.fact"]["id"] == "fact-id"
