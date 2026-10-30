# -*- coding: utf-8 -*-
"""The Mirror state card: computed from the Vault on every read, no model call.

Rows are written through the real stores on an isolated SQLite student.
"""
import json
from unittest.mock import AsyncMock, patch

from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.memory.vault_items import VaultItemService
from app.pai_c.mirror import MirrorEngine, card_version
from app.pai_c.policy import controller
from scripts.counselor_eval_support import StudentSession

POLICY = controller.load_data("areas_policy.json")
PRIORITY = POLICY["priority"]
QUOTE = "VERBATIM-QUOTE-XYZ"


def _record(db, ws, kind, value, **evidence):
    candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type="student_record", key=kind,
        proposed_value=value, confidence=0.95, source_type="user_explicit",
        evidence={"quote": QUOTE, **evidence}, allow_user_explicit=True)
    result = MemoryReconciler(db).reconcile(candidate)
    assert result.accepted, result
    db.commit()
    return result.result_id


def _education(db, ws):
    _record(db, ws, "education", {"qualification_name": "Matric", "field_of_study": "Science",
                                  "academic_status": "completed"}, capture="onboarding")
    return _record(db, ws, "education", {"qualification_name": "FSc", "field_of_study": "Pre-Engineering",
                                         "academic_status": "current", "result": {"percentage": 82}},
                   capture="onboarding")


def _item(db, ws, item_type, value, *, level="stated"):
    item = VaultItemService(db).apply(ws, item_type, value, source_type="conversation", level=level,
        confidence=0.9, evidence={"quote": QUOTE}, candidate_id=None).item
    db.commit()
    return item


def _area(card, key):
    return next(area for area in card["areas"] if area["key"] == key)


def test_mirror_not_ready_shows_known_areas():
    with StudentSession() as student, student.factory() as db:
        _education(db, student.workspace_id)
        card = MirrorEngine(db).build(student.workspace_id)
    assert set(card) == {"version", "header", "areas", "unknowns", "text", "ready"}
    assert card["ready"] is False and card["text"] is None
    assert [area["key"] for area in card["areas"]] == PRIORITY
    assert all(area["label"] == POLICY["labels"][area["key"]] for area in card["areas"])
    history, status = _area(card, "history"), _area(card, "status")
    assert history["level"] >= 1 and status["level"] >= 1 and history["entries"]
    for area in card["areas"]:
        if area["key"] not in ("history", "status"):
            assert area["level"] == 0 and area["entries"] == [] and area["tension"] == []
    assert {u["area"] for u in card["unknowns"]} == set(PRIORITY) - {"history", "status"}
    assert card["unknowns"][0]["area"] == "goals"
    entry = history["entries"][0]
    assert set(entry) == {"id", "text", "evidence", "source_label", "observed_at"}
    assert entry["source_label"] == "Onboarding" and entry["observed_at"]
    assert card["header"]["education_line"]["percent"] == 82


def test_area_levels_from_evidence():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "value", {"text": "Helping people"})
        _item(db, ws, "strength", {"text": "Mathematics"}, level="shown")
        _item(db, ws, "interest", {"text": "Robotics"}, level="shown")
        _item(db, ws, "interest", {"text": "Circuits"}, level="shown")
        card = MirrorEngine(db).build(ws)
    assert _area(card, "values")["level"] == 1
    assert _area(card, "strengths")["level"] == 2
    assert _area(card, "interests")["level"] == 3
    assert _area(card, "pressures")["level"] == 0
    assert [e["evidence"] for e in _area(card, "interests")["entries"]] == ["shown", "shown"]


def test_entries_use_catalog_labels_never_codes():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _education(db, ws)
        _item(db, ws, "option", {"text": "Medicine", "status": "ruled_out"})
        _item(db, ws, "pressure", {"text": "Fees are high", "kind": "money"})
        _item(db, ws, "family_member", {"relation": "father", "influence": "high", "wish": "Engineering"})
        _item(db, ws, "family_member", {"relation": "mother", "occupation": "Teacher"})
        card = MirrorEngine(db).build(ws)
    assert QUOTE not in json.dumps(card)
    # Codes may sit beside their labels as keys (the header's education line,
    # shaped like the roadmap's); everything rendered as text is labels.
    text = json.dumps(card["areas"]) + card["header"]["education_line"]["text"]
    for code in ("ruled_out", "\"money\"", "father", "pre_engineering"):
        assert code not in text, code
    options = [e["text"] for e in _area(card, "options")["entries"]]
    assert any("Ruled out" in line for line in options)
    family = " ".join(e["text"] for e in _area(card, "family_social")["entries"])
    assert "Father" in family and "Mother" in family
    history = " ".join(e["text"] for e in _area(card, "history")["entries"])
    assert "Pre-Engineering" in history and "82%" in history


def test_education_bars_from_subject_marks():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        education_id = _education(db, ws)
        _record(db, ws, "course", {"education_id": education_id, "name": "Physics",
                                   "score": {"percentage": 78}})
        _record(db, ws, "course", {"education_id": education_id, "name": "Mathematics",
                                   "score": {"marks_obtained": 90, "marks_total": 100}})
        card = MirrorEngine(db).build(ws)
    bars = sorted(_area(card, "history")["bars"], key=lambda bar: bar["label"])
    assert bars == [{"label": "Mathematics", "percent": 90}, {"label": "Physics", "percent": 78}]
    assert _area(card, "goals")["bars"] == []


def test_tension_family_vs_goal():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        father = _item(db, ws, "family_member", {"relation": "father", "wish": "Wants me to become a doctor"})
        _item(db, ws, "family_member", {"relation": "mother", "occupation": "Teacher"})
        goal = _record(db, ws, "goal", {"goal_type": "study", "title": "Computer Science",
                                        "details": {"field_of_study": "computer_science"}})
        card = MirrorEngine(db).build(ws)
        mark = {"a_id": "item:" + father.id, "b_id": "goal:" + goal, "note_key": "tension.family_vs_goal"}
        assert _area(card, "family_social")["tension"] == [mark]
        assert _area(card, "goals")["tension"] == [mark]
        assert _area(card, "interests")["tension"] == []
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "family_member", {"relation": "father", "wish": "Medicine"})
        _item(db, ws, "family_member", {"relation": "mother", "occupation": "Teacher"})
        _record(db, ws, "goal", {"goal_type": "study", "title": "MBBS",
                                 "details": {"field_of_study": "mbbs"}})
        card = MirrorEngine(db).build(ws)
    assert _area(card, "family_social")["tension"] == [] and _area(card, "goals")["tension"] == []
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "family_member", {"relation": "father", "wish": "Wants me to be happy"})
        _item(db, ws, "family_member", {"relation": "mother", "occupation": "Teacher"})
        _record(db, ws, "goal", {"goal_type": "study", "title": "Computer Science"})
        card = MirrorEngine(db).build(ws)
    assert _area(card, "family_social")["tension"] == []  # a wish no field matches is no tension


def test_version_changes_only_when_entries_change():
    from app.journey import JourneyService
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _education(db, ws)
        first = MirrorEngine(db).build(ws)
        assert isinstance(first["version"], str) and first["version"] == card_version(first)
        assert MirrorEngine(db).build(ws)["version"] == first["version"]
        # Stored text and a Vault fact outside every area leave the card as it was.
        journey = JourneyService(db).ensure_counselor(ws)
        JourneyService(db).set_mirror_text(ws, "You study FSc. You lean toward fields. You weigh options.",
                                           first["version"])
        db.commit()
        candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type="vault_fact",
            key="preferences.target_countries", proposed_value=["Pakistan"], confidence=0.9,
            source_type="user_explicit", evidence={"quote": QUOTE}, allow_user_explicit=True)
        MemoryReconciler(db).reconcile(candidate)
        db.commit()
        same = MirrorEngine(db).build(ws)
        assert same["version"] == first["version"] and same["text"] is not None
        _item(db, ws, "interest", {"text": "Robotics"})
        changed = MirrorEngine(db).build(ws)
        assert journey is not None
    assert changed["version"] != first["version"]
    # A re-sighting moves observed_at only: the card is the same.
    seen_again = json.loads(json.dumps(changed))
    for area in seen_again["areas"]:
        for entry in area["entries"]:
            entry["observed_at"] = "2030-01-01T00:00:00+00:00"
    assert card_version(seen_again) == changed["version"]


def test_engine_makes_no_model_call():
    boom = AsyncMock(side_effect=AssertionError("the Mirror engine must not call a model"))
    with StudentSession() as student, student.factory() as db, \
            patch("app.inference.gateway.complete", boom), \
            patch("app.inference.gateway.embed", boom):
        ws = student.workspace_id
        _education(db, ws)
        _item(db, ws, "interest", {"text": "Robotics"})
        card = MirrorEngine(db).build(ws)
    assert card["areas"] and boom.await_count == 0
    # A `from app.inference.gateway import complete` would dodge the patch above.
    from pathlib import Path
    from app.pai_c.mirror import engine
    assert "app.inference" not in Path(engine.__file__).read_text(encoding="utf-8")


def test_summary_and_workspace_picture_read_the_card():
    from app.models import Workspace
    from app.routers.counselor_summary import current_summary
    from app.routers.counselor_workspace import counselor_workspace
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _education(db, ws)
        workspace = db.get(Workspace, ws)
        with patch("app.routers.counselor_summary._authorized", return_value=workspace):
            summary = current_summary(ws, db, None, None)["data"]
        with patch("app.routers.counselor_workspace._authorized", return_value=workspace):
            data = counselor_workspace(ws, db, None, None)["data"]
        card = MirrorEngine(db).build(ws)
    assert summary == {"type": "mirror_state", "card": card}
    assert data["picture"] == {"header": card["header"], "unknowns": card["unknowns"], "text": None,
                               "ready": False, "version": card["version"]}
    for kept in ("moments", "ratings", "coverage", "completeness"):
        assert kept in data
    # The confirm gate is gone (Task 3): no Mirror status, and no ratings to show.
    assert "mirror_status" not in data and data["ratings"] == []


def test_ready_needs_the_current_education_a_goal_and_two_interests_not_a_second_history_entry():
    """Onboarding records only the current education; the card must become
    ready from that plus a goal and two interests (FOUR_FEATURES_SPEC 6)."""
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _record(db, ws, "education", {"qualification_name": "FSc", "field_of_study": "Pre-Engineering",
                                      "academic_status": "current", "result": {"percentage": 78}},
                capture="onboarding")
        _record(db, ws, "goal", {"goal_type": "study", "title": "Electrical Engineering"})
        _item(db, ws, "interest", {"text": "Robotics"})
        assert MirrorEngine(db).ready(ws) is False
        _item(db, ws, "interest", {"text": "Circuits"})
        card = MirrorEngine(db).build(ws)
        assert card["ready"] is True
        assert "history" in {u["area"] for u in card["unknowns"]}  # the past is still asked for, it just never gates the card
