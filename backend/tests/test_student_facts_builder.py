"""P1-T4 Task 4 (R-13, R-14): the Counsellor builds StudentFactsV1 from the Vault (real SQLite rows), with evidence,
the privacy allow-list and eligible levels."""

import pytest

from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.memory.student_records import StudentRecordService
from app.models import VaultVersion
from app.os.contracts.student_facts import StudentFactsV1
from app.pai_c.connect import student_facts
from scripts.counselor_eval_support import StudentSession

pytestmark = [pytest.mark.req("R-13"), pytest.mark.req("R-14")]

FSC = {"qualification_name": "fsc", "field_of_study": "pre_engineering", "academic_status": "current"}
SHOWN = {"authority": "institution_issued", "file_id": "file-1"}


def education(db, ws, values, source_type="user_explicit", evidence=None):
    StudentRecordService(db).apply(ws, "education", values, source_type=source_type, claim_origin="student",
                                   capture_method="explicit_correction", evidence=evidence)
    db.commit()


def item(db, ws, key, value):
    candidate = MemoryCandidateService(db).propose(
        ws, "vault_item", key=key, proposed_value=value, confidence=0.9, source_type="user_explicit",
        allow_user_explicit=True, input_channel="profile", evidence={"quote": "q", "capture": "details"})
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()


def facts_of(built):
    return {f["key"]: f for f in built["facts"]}


def build(db, ws):
    built = student_facts.build(db, ws)
    StudentFactsV1.model_validate(built)  # the contract is checked in tests only
    return built


def test_fsc_student_is_eligible_for_bachelor():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, FSC)
        assert build(db, s.workspace_id)["eligible_levels"] == ["bachelor"]


def test_matric_student_is_eligible_for_intermediate():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {"qualification_name": "matric", "academic_status": "completed"})
        assert build(db, s.workspace_id)["eligible_levels"] == ["intermediate"]


def test_masters_student_is_eligible_for_master_and_phd():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {"qualification_name": "masters", "academic_status": "completed"})
        assert build(db, s.workspace_id)["eligible_levels"] == ["master", "phd"]


def test_no_education_gives_none_and_still_validates():
    with StudentSession() as s, s.factory() as db:
        built = build(db, s.workspace_id)
        assert built["eligible_levels"] is None and built["facts"] == []


def test_stated_mark_is_a_stated_fact_with_zero_version_when_no_counter():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {**FSC, "result": {"marks_obtained": 800, "marks_total": 1100}})
        facts = facts_of(build(db, s.workspace_id))
        mark = facts["education.intermediate.marks_obtained"]
        assert mark["value"] == 800 and mark["evidence"] == "stated" and mark["vault_version"] == 0
        assert mark["document_ref"] is None and mark["as_of"] is not None


def test_inferred_mark_is_unknown_with_no_value():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {**FSC, "result": {"marks_obtained": 900, "marks_total": 1100}},
                  source_type="document", evidence={"ocr": True, "file_id": "file-2"})
        mark = facts_of(build(db, s.workspace_id))["education.intermediate.marks_obtained"]
        assert mark["evidence"] == "unknown" and mark["value"] is None


def test_shown_mark_carries_document_ref():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {**FSC, "result": {"marks_obtained": 850, "marks_total": 1100}},
                  source_type="document", evidence=SHOWN)
        mark = facts_of(build(db, s.workspace_id))["education.intermediate.marks_obtained"]
        assert mark["evidence"] == "shown" and mark["document_ref"] == "file-1" and mark["value"] == 850


def test_part_marks_use_the_shared_key_map():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {**FSC, "result": {"part1": {"marks_obtained": 400, "marks_total": 550}}})
        facts = facts_of(build(db, s.workspace_id))
        assert facts["education.intermediate.part1.marks_obtained"]["value"] == 400


def test_versions_come_from_key_versions_and_never_exceed_the_top():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, {**FSC, "result": {"marks_obtained": 800}})
        db.add(VaultVersion(workspace_id=s.workspace_id, version=7,
                            key_versions={"education.intermediate.marks_obtained": 5}))
        db.commit()
        built = build(db, s.workspace_id)
        assert built["vault_version"] == 7
        facts = facts_of(built)
        assert facts["education.intermediate.marks_obtained"]["vault_version"] == 5
        assert facts["education.intermediate.level"]["vault_version"] == 0


def test_test_score_budget_domicile_place_field_order_and_exclusions():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        education(db, ws, FSC)
        StudentRecordService(db).apply(ws, "test_attempt", {"test_type": "MDCAT", "overall_score": "165"},
                                       source_type="user_explicit", claim_origin="student",
                                       capture_method="explicit_correction")
        db.commit()
        item(db, ws, "domicile", {"province": "punjab", "area": "urban"})
        item(db, ws, "place_preference", {"scope": "abroad", "fallback": "none", "regions": []})
        item(db, ws, "field_order", {"fields": ["Pharm-D", "No Such Field"]})
        item(db, ws, "option", {"text": "Pharm-D", "status": "ruled_out"})
        built = build(db, ws)
        facts = facts_of(built)
        assert facts["test.mdcat.score"]["value"] == 165
        assert facts["constraint.domicile"]["value"] == "punjab"
        assert facts["preference.place"]["value"] == {"scope": "abroad", "fallback": "none", "regions": []}
        assert facts["constraint.field_order"]["value"] == ["pharm_d"]
        assert facts["constraint.excluded_fields"]["value"] == ["pharm_d"]


def test_inferred_item_is_unknown():
    from sqlalchemy import select
    from app.models import VaultItem
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        item(db, ws, "domicile", {"province": "sindh"})
        row = db.scalar(select(VaultItem).where(VaultItem.workspace_id == ws, VaultItem.item_type == "domicile"))
        row.level = "inferred"
        db.commit()
        fact = facts_of(build(db, ws))["constraint.domicile"]
        assert fact["evidence"] == "unknown" and fact["value"] is None


def test_no_identity_or_guardian_key_and_no_budget_amount():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        education(db, ws, FSC)
        for key, value in (("identity.date_of_birth", "2008-01-01"), ("identity.full_name", "A B"),
                           ("finance.budget", {"band": "1_3_lakh", "amount": 250000})):
            candidate = MemoryCandidateService(db).propose(
                ws, "vault_fact", key=key, proposed_value=value, confidence=0.9, source_type="user_explicit",
                allow_user_explicit=True, input_channel="profile", evidence={"quote": "q", "capture": "details"})
            MemoryReconciler(db).reconcile(candidate)
        db.commit()
        built = build(db, ws)
        keys = [f["key"] for f in built["facts"]]
        assert not any(k.startswith(("identity", "guardian", "name", "dob")) for k in keys)
        assert "constraint.budget" in keys
        assert "250000" not in repr(built) and "2008" not in repr(built)
        assert facts_of(built)["constraint.budget"]["value"] == "1_3_lakh"


def test_inferred_education_alone_gives_no_eligible_levels():
    with StudentSession() as s, s.factory() as db:
        education(db, s.workspace_id, FSC, source_type="document", evidence={"ocr": True, "file_id": "f9"})
        assert build(db, s.workspace_id)["eligible_levels"] is None


def test_current_record_beats_a_newer_completed_one_of_the_same_family():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        education(db, ws, {"qualification_name": "fsc", "institution_name": "A", "academic_status": "current",
                           "result": {"marks_obtained": 700}})
        education(db, ws, {"qualification_name": "ics", "institution_name": "B", "academic_status": "completed",
                           "result": {"marks_obtained": 900}})
        assert facts_of(build(db, ws))["education.intermediate.marks_obtained"]["value"] == 700


def test_unmapped_province_is_dropped():
    with StudentSession() as s, s.factory() as db:
        item(db, s.workspace_id, "domicile", {"province": "Atlantis"})
        assert "constraint.domicile" not in facts_of(build(db, s.workspace_id))
