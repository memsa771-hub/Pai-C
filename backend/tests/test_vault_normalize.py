# -*- coding: utf-8 -*-
"""Normalize: every candidate leaves in English, codes, ASCII digits and ISO dates."""

import pytest
from sqlalchemy import select

from app.memory.candidates import MemoryCandidateService
from app.memory.errors import MemoryDataError
from app.memory.normalize import ascii_digits, detect_language, iso_date, normalize_candidate
from app.models import VaultDrop
from scripts.counselor_eval_support import StudentSession


@pytest.mark.parametrize("text,expected", [
    ("Hi, I'm Ayesha. I just finished FSc Pre-Medical from Faisalabad board.", "en"),
    ("Mera naam Bilal hai aur main Lahore mein rehta hoon.", "roman_ur"),
    ("Bro mera FSc pre-eng ka result 88% aaya, Federal board. ECAT next month hai.", "mixed"),
    ("میرا نام بلال ہے", "ur"),
    ("My name is بلال", "mixed"),
])
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_ascii_digits():
    assert ascii_digits("۱۰۴۵") == "1045"
    assert ascii_digits("١٢٣") == "123"


def test_iso_date_pakistani_order():
    assert iso_date("14 August 2007") == "2007-08-14"
    assert iso_date("14/08/2007") == "2007-08-14"
    assert iso_date("August 2007") == "2007-08"
    assert iso_date("someday") is None


def test_choice_fields_become_codes():
    r = normalize_candidate("student_record", "education",
                            {"details": {"awarding_body": "Lahore board"}, "field_of_study": "Pre-Medical"},
                            student_text="")
    assert r.rejected_reason is None
    assert r.value["details"]["awarding_body"] == "bise_lahore"
    unknown = normalize_candidate("student_record", "education",
                                  {"details": {"awarding_body": "Some Academy"}}, student_text="")
    assert unknown.value["details"]["awarding_body"] == "Some Academy"


def test_urdu_script_value_is_rejected_and_logged():
    r = normalize_candidate("student_record", "education", {"institution": "لاہور کالج"}, student_text="")
    assert r.rejected_reason == "not_english: institution"
    with StudentSession() as student, student.factory() as db:
        with pytest.raises(MemoryDataError):
            MemoryCandidateService(db).propose(
                student.workspace_id, "student_record", key="education",
                proposed_value={"institution": "لاہور کالج"}, source_type="conversation",
                input_channel="conversation", source_event_ids=["evt-1"])
        drop = db.scalar(select(VaultDrop))
        assert (drop.source, drop.stage, drop.source_ref) == ("chat", "normalize", "evt-1")
        assert drop.reason == "not_english: institution"


def test_urdu_script_name_is_kept_as_a_guess():
    r = normalize_candidate("vault_fact", "identity.full_name", "بلال", student_text="")
    assert r.rejected_reason is None and r.needs_confirmation and r.value == "بلال"
    with StudentSession() as student, student.factory() as db:
        c = MemoryCandidateService(db).propose(
            student.workspace_id, "vault_fact", key="identity.full_name", proposed_value="بلال",
            evidence={"quote": "میرا نام بلال ہے"})
        assert c.evidence["inferred"] is True and c.evidence["source_language"] == "ur"


def test_rupees_become_pkr():
    for word in ("rupees", "Rs", "روپے"):
        r = normalize_candidate("vault_fact", "finance.budget", {"amount": "۲۵۰۰۰", "currency": word}, student_text="")
        assert r.value == {"amount": "25000", "currency": "PKR"}


def test_empty_budget_is_rejected():
    r = normalize_candidate("vault_fact", "finance.budget", {"currency": "PKR"}, student_text="")
    assert r.rejected_reason == "empty_budget"


def test_dates_and_semantic_memory_skipped():
    r = normalize_candidate("vault_fact", "identity.date_of_birth", "14/08/2007", student_text="")
    assert r.value == "2007-08-14"
    r = normalize_candidate("student_record", "education", {"start_date": "March 2020", "x": "keep"}, student_text="")
    assert r.value["start_date"] == "2020-03"
    with StudentSession() as student, student.factory() as db:
        c = MemoryCandidateService(db).propose(student.workspace_id, "semantic_memory", content="لاہور")
        assert c.evidence is None


def test_family_member_name_in_urdu_is_a_guess():
    r = normalize_candidate("vault_item", "family_member", {"name": "احمد", "relation": "Father"}, student_text="")
    assert r.rejected_reason is None and r.needs_confirmation
    r = normalize_candidate("vault_item", "family_member", {"notes": "احمد"}, student_text="")
    assert r.rejected_reason == "not_english: notes"


def test_arabic_value_inside_a_list_is_rejected_with_its_path():
    r = normalize_candidate("student_record", "education", {"details": {"subjects": ["Physics", "کیمیا"]}}, student_text="")
    assert r.rejected_reason == "not_english: details.subjects"


def test_drop_source_mapping_and_file_id_ref():
    from app.memory.catalog import vault_catalog
    story = next(t.key for t in vault_catalog().types() if t.shown_on == "story" and t.storage == "record")
    with StudentSession() as student, student.factory() as db:
        svc = MemoryCandidateService(db)
        for key, channel, extra in (("education", "document", {"evidence": {"file_id": "file-9"}}),
                                    (story, "profile", {}), ("education", "profile", {})):
            with pytest.raises(MemoryDataError):
                svc.propose(student.workspace_id, "student_record", key=key, proposed_value={"institution": "لاہور"},
                            source_type="document" if channel == "document" else "conversation",
                            input_channel=channel, **extra)
        rows = db.scalars(select(VaultDrop).order_by(VaultDrop.created_at)).all()
        assert [(r.source, r.source_ref) for r in rows] == [("document", "file-9"), ("story", None), ("details", None)]


def test_drop_survives_callers_rollback():
    with StudentSession() as student, student.factory() as db:
        with pytest.raises(MemoryDataError):
            MemoryCandidateService(db).propose(
                student.workspace_id, "student_record", key="education",
                proposed_value={"institution": "لاہور"})
        db.rollback()
        assert db.scalar(select(VaultDrop.reason)) == "not_english: institution"


def test_retract_is_not_normalized():
    with StudentSession() as student, student.factory() as db:
        c = MemoryCandidateService(db).propose(
            student.workspace_id, "vault_fact", key="identity.full_name", operation="retract")
        assert c.evidence is None


def test_extract_loop_continues_past_a_rejected_candidate():
    import asyncio
    from types import SimpleNamespace
    from app.memory.handlers import extract_memory
    with StudentSession() as student, student.factory() as db:
        job = SimpleNamespace(id="j1", workspace_id=student.workspace_id, payload={"candidates": [
            {"candidate_type": "student_record", "key": "education", "proposed_value": {"institution": "لاہور"}},
            {"candidate_type": "vault_fact", "key": "location.current_city", "proposed_value": "Lahore"}]})
        result = asyncio.run(extract_memory(job, db))
        assert result["candidates_proposed"] == 1
        assert db.scalar(select(VaultDrop.reason)) == "not_english: institution"
