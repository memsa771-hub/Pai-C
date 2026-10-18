"""The same ten areas use student evidence from conversation, taps and uploads."""
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import MemoryCandidate
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.memory import MemoryService
from app.pai_c.policy.classifier import Signals, fallback_signals
from app.pai_c.understanding.views import coverage_areas
from tests.test_student_profile_api import api, HEADERS
from tests.truth_map_fixtures import item


def coverage(data=None, facts=None, records=None):
    return coverage_areas(CounselorNotebookData.model_validate(data or {}),
                          SimpleNamespace(facts=facts or {}, records=records or {}))


def test_empty_profile_has_ten_uncovered_areas():
    areas = coverage()
    assert set(areas) == {"status", "history", "interests", "strengths", "family_social",
                          "values", "pressures", "sure", "goals", "options"}
    assert not any(area["covered"] for area in areas.values())


@pytest.mark.parametrize("category,covered", [("self", True), ("family", True), ("unknown", False)])
def test_goal_requires_evidence_of_whose_wish_it_is(category, covered):
    goal = item(key="goal.direction", category=category, evidence="I want to build things")
    assert coverage({"source": [goal]})["goals"]["covered"] is covered
    goal["status"] = "retired"
    assert not coverage({"source": [goal]})["goals"]["covered"]


def test_family_wish_and_own_wish_are_separate_evidenced_items():
    notebook = CounselorNotebookData.model_validate({"source": [
        item(id="own", key="goal.own", value="Creative work", category="self", evidence="I want creative work"),
        item(id="family", key="goal.family", value="A stable profession", category="family", evidence="My guardian wants a stable profession"),
    ]})
    assert notebook.source[0].category == "self"
    assert notebook.source[1].category == "family"
    assert coverage_areas(notebook, SimpleNamespace(facts={}, records={}))["goals"]["item_count"] == 2


@pytest.mark.parametrize("key", ["option.known", "myth.belief"])
def test_options_and_reported_myths_count_as_student_evidence_only(key):
    assert coverage({"said": [item(key=key, evidence="I have heard of this path")]})["options"]["covered"]
    with pytest.raises(ValidationError):
        CounselorNotebookData.model_validate({"said": [item(key=key, evidence="")]})


def test_identity_name_is_not_current_status_and_bare_rows_are_not_coverage():
    assert not coverage(facts={"identity.full_name": {"value": "Student", "evidence": {"quote": "My name is Student"}}})["status"]["covered"]
    result = coverage(facts={"identity.current_status": {"value": "Studying"}}, records={"education": [{"id": "empty-shell"}]})
    assert not result["status"]["covered"] and result["history"]["item_count"] == 0


@pytest.mark.parametrize("text", ["I want practical work", "Mujhe practical kaam karna hai"])
def test_classifier_accepts_the_two_new_areas_without_language_logic(text):
    raw = fallback_signals().model_dump()
    raw.update(mentioned_areas=["goals", "options"], declined_area="options",
               request={"text": text, "kind": "decision_help", "needs_research": False, "needs_context": False})
    assert Signals.model_validate_json(json.dumps(raw)).mentioned_areas == ["goals", "options"]
    raw["mentioned_areas"] = ["invented_area"]
    with pytest.raises(ValidationError):
        Signals.model_validate(raw)


def test_tap_choices_use_existing_reconciled_profile_api(api):
    client, db, workspace_id = api
    for payload in [
        {"field_key": "location.current_city", "value": "Student's city"},
        {"record_type": "education", "value": {"qualification_name": "Upper secondary",
          "canonical_level": "upper_secondary", "academic_status": "current", "details": {"awarding_body": "Student's board"}}},
        {"record_type": "skill", "value": {"name": "Repairing devices"}},
    ]:
        response = client.post(f"/v1/student-profile/edits?network={workspace_id}", headers=HEADERS,
                               json={**payload, "reason": "Selected by the student on a tap card"})
        assert response.status_code == 200, response.text
    rows = db.scalars(select(MemoryCandidate)).all()
    assert len(rows) == 3 and all(row.status == "accepted" for row in rows)
    result = coverage_areas(CounselorNotebookData(), MemoryService(db).profile(workspace_id))
    assert result["status"]["covered"] and result["strengths"]["covered"]
    assert result["history"]["item_count"] == 1


def test_upload_candidates_count_only_after_reconciliation(api):
    _, db, workspace_id = api
    service = MemoryCandidateService(db)
    values = [
        ("education", {"qualification_name": "Current qualification", "academic_status": "current"}),
        ("test_attempt", {"test_type": "Entrance assessment", "overall_score": "Recorded result"}),
        ("certification", {"name": "Practical skills certificate"}),
    ]
    candidates = [service.propose(workspace_id=workspace_id, candidate_type="student_record", key=key,
        proposed_value=value, confidence=0.95, source_type="document", input_channel="document",
        evidence={"quote": "Printed record supplied by the student", "authority": "institution_issued", "locator": "p1"})
        for key, value in values]
    before = coverage_areas(CounselorNotebookData(), MemoryService(db).profile(workspace_id))
    assert not any(before[key]["covered"] for key in ("status", "history", "strengths"))
    for candidate in candidates:
        result = MemoryReconciler(db).reconcile(candidate)
        assert result.accepted, result.reason
    after = coverage_areas(CounselorNotebookData(), MemoryService(db).profile(workspace_id))
    assert all(after[key]["covered"] for key in ("status", "history", "strengths"))
