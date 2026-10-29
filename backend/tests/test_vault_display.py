# -*- coding: utf-8 -*-
"""Audit #4 and #6: every Vault value reads through the catalog, one line per
entry, on the Vault page and in path evidence alike. No raw code, no internal
value (600000, pre_engineering, ruled_out, high, considering) on any page."""

import re

from app.memory.student_records import StudentRecordService
from app.memory.vault import VaultService
from app.memory.vault_items import VaultItemService
from app.memory.vault_view import VaultView, display_text
from app.models import ExternalInfluence, StudentGoal
from scripts.eval_vault import VaultSession

# Codes and bare enum tokens the fixtures below store; none may be shown.
RAW = ("pre_engineering", "upper_secondary", "ruled_out", "3_6_lakh", "per_year", "career_suggestion",
       "partially_aligned", "600000", "300000")
BARE = ("high", "considering", "current", "fsc", "education", "parent")


def _leaks(text: str) -> list[str]:
    found = [code for code in RAW if code in text]
    found += [token for token in BARE if re.search(rf"(?<![\w-]){token}(?![\w-])", text)]
    return found


def _seed(db, ws):
    VaultService(db).apply_fact(ws, "finance.budget", {"min": 300000, "max": 600000, "currency": "PKR",
                                                       "period": "per_year"},
                                "conversation", evidence={"quote": "3 se 6 lakh"})
    StudentRecordService(db).apply(
        ws, "education", {"qualification_name": "fsc", "field_of_study": "pre_engineering",
                          "academic_status": "current", "canonical_level": "upper_secondary",
                          "result": {"marks_obtained": 470, "marks_total": 550}},
        source_type="conversation", claim_origin="student", capture_method="conversation_extraction",
        evidence={"quote": "FSc pre-engineering, 470/550"})
    db.add(StudentGoal(workspace_id=ws, goal_type="education", title="engineering", commitment="considering",
                       details={"field_of_study": "engineering"}, source_type="conversation",
                       claim_origin="student", capture_method="chat", status="active"))
    db.add(ExternalInfluence(workspace_id=ws, influencer_type="parent", source_label="Father",
                             suggested_direction="Engineering", influence_type="career_suggestion",
                             student_alignment="partially_aligned", source_type="conversation",
                             claim_origin="student", capture_method="chat", status="active"))
    items = VaultItemService(db)
    for item_type, value in (("family_member", {"relation": "father", "wish": "Wants him to study engineering",
                                                "influence": "high"}),
                             ("option", {"text": "Medicine", "status": "ruled_out"}),
                             ("strength", {"text": "Good at maths", "basis": "Top marks in maths"})):
        items.apply(ws, item_type, value, source_type="conversation", level="stated", confidence=0.9,
                    evidence={"quote": "q"}, candidate_id=None)
    db.commit()


def _all_entries(view):
    entries = [e for section in view["details"].values() for e in section["entries"]]
    return entries + [e for card in view["story"] for e in card["entries"]]


def test_4_vault_view_shows_labels_never_codes():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        entries = {e["type"]: e for e in _all_entries(VaultView(db).build(ws))}
    assert entries["finance.budget"]["display"] == "3-6 lakh, per year"
    assert "470/550 (85%)" in entries["education"]["display"]
    assert entries["education"]["display"].startswith("FSc, Pre-Engineering")
    assert entries["goal"]["display"] == "Engineering, Considering"
    assert entries["family_member"]["display"] == "Father, Wants him to study engineering, High influence"
    assert entries["strength"]["display"] == "Good at maths — Top marks in maths"
    for entry in entries.values():
        assert not _leaks(entry["display"]), (entry["type"], entry["display"])


def test_4_path_evidence_reads_as_the_vault_page():
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.paths.analyzer import _evidence_index
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        index = _evidence_index(db, ws, CounselorNotebookData())
    assert index, "the fixtures give path evidence"
    for ref, text in index.items():
        assert not _leaks(text), (ref, text)
    assert any("470/550 (85%)" in text for text in index.values())


def test_4_budget_amount_reads_as_lakh_when_no_band_fits():
    assert display_text("finance.budget", {"min": 300000, "max": 800000}) == "3-8 lakh"
    assert display_text("finance.budget", {"amount": 250000}) == "1-3 lakh"
    assert display_text("education", {"qualification_name": "matric", "result": {"percentage": 85}}) == "Matric, 85%"


def test_4_budget_in_another_currency_is_never_a_lakh_band():
    assert display_text("finance.budget", {"amount": 20000, "currency": "USD"}) == "20000 USD"
    assert display_text("finance.budget", {"min": 5000, "max": 8000, "currency": "USD", "period": "per_year"}) == (
        "5000-8000 USD, per year")
    assert display_text("finance.budget", {"amount": 250000, "currency": "PKR"}) == "1-3 lakh"
