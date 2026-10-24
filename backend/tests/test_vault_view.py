# -*- coding: utf-8 -*-
"""One read model of the whole Vault: badges, document links, freshness, conflicts.

Rows are written through the real stores (items, facts, records) where the
store decides something the view must show, and inserted directly where only
the timestamps matter (freshness).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.memory.catalog import vault_catalog
from app.memory.evidence import evidence_policy, value_digest
from app.memory.student_records import StudentRecordService
from app.memory.vault import VaultService
from app.memory.vault_items import VaultItemService
from app.memory.vault_view import VaultView, badge_for, level_of, view_copy
from app.models import FileRecord, ProfileIssue, StudentGoal, VaultFact
from scripts.eval_vault import VaultSession

SECRET = "Mera domicile Sindh ka hai SECRET-QUOTE"
DOC = {"authority": "institution_issued", "quote": SECRET, "locator": "p2", "source_language": "roman_ur"}


def _file(db, ws, name="result_card.pdf"):
    record = FileRecord(id=str(uuid.uuid4()), workspace_id=ws, filename=name, content_type="application/pdf",
                        size=10, storage_key=f"k/{name}", uploaded_by="human:user", status="active")
    db.add(record)
    db.flush()
    return record


def _item(db, ws, item_type, value, *, source_type="conversation", level="stated", evidence=None, **kw):
    return VaultItemService(db).apply(
        ws, item_type, value, source_type=source_type, level=level, confidence=0.9,
        evidence=evidence or {"quote": SECRET, "source_language": "roman_ur"}, candidate_id=None, **kw)


def _entries(view, type_key):
    found = [e for section in view["details"].values() for e in section["entries"] if e["type"] == type_key]
    found += [e for card in view["story"] if card["type"] == type_key for e in card["entries"]]
    return found


def _entry(view, type_key):
    entries = _entries(view, type_key)
    assert len(entries) == 1, entries
    return entries[0]


def test_badges_for_each_level():
    assert [badge_for(level, False) for level in ("inferred", "stated", "shown", "confirmed")] == [
        "PAI's guess", "Stated", "From document", "Confirmed"]
    assert {badge_for(level, True) for level in ("inferred", "stated", "shown", "confirmed")} == {"In question"}

    assert level_of("conversation", None, {"quote": "x"}) == "stated"
    assert level_of("user_explicit", "self_reported", {}) == "stated"
    assert level_of("agent", None, {}) == "inferred"
    assert level_of("conversation", None, {"inferred": True}) == "inferred"
    assert level_of("document", "document_supported", {"file_id": "f", "authority": "institution_issued"}) == "shown"
    assert level_of("document", None, {"file_id": "f", "authority": "institution_issued"}) == "shown"
    assert level_of("document", "extracted", {"file_id": "f", "authority": "student_authored"}) == "stated"
    confirmation = {"confirmation": {"value_digest": value_digest("Ali"), "confirmed_at": "2026-10-01T00:00:00"}}
    assert level_of("user_explicit", None, confirmation, value="Ali",
                    capture_method=evidence_policy()["confirmation_capture"]) == "confirmed"

    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "interest", {"text": "Robotics"}, level="inferred")
        _item(db, ws, "strength", {"text": "Patience"})
        f = _file(db, ws)
        _item(db, ws, "domicile", {"province": "punjab"}, source_type="document", level="shown",
              evidence={**DOC, "file_id": f.id})
        quota = _item(db, ws, "quota", {"kind": "disabled"}).item
        VaultItemService(db).confirm(ws, quota.id)
        db.commit()
        view = VaultView(db).build(ws)
        assert _entry(view, "interest")["badge"] == "PAI's guess"
        assert _entry(view, "strength")["badge"] == "Stated"
        assert _entry(view, "domicile")["badge"] == "From document"
        assert _entry(view, "quota")["badge"] == "Confirmed"
        assert _entry(view, "quota")["confirmed_at"]
        assert {e["level"] for e in (_entry(view, k) for k in ("interest", "strength", "domicile", "quota"))} == {
            "inferred", "stated", "shown", "confirmed"}


def test_document_entry_has_file_link():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        f = _file(db, ws, "domicile_certificate.pdf")
        _item(db, ws, "domicile", {"province": "sindh", "area": "urban"}, source_type="document", level="shown",
              evidence={**DOC, "file_id": f.id, "page": 2})
        StudentRecordService(db).apply(
            ws, "education", {"qualification_name": "hssc", "institution_name": "BISE Lahore"},
            source_type="document", claim_origin="institution_document", capture_method="document_extraction",
            evidence={**DOC, "file_id": f.id, "locator": "p3"}, verification_status="document_supported")
        db.commit()

        view = VaultView(db).build(ws)
        domicile = _entry(view, "domicile")
        assert domicile["document"] == {"file_id": f.id, "page": 2, "filename": "domicile_certificate.pdf"}
        assert domicile["kind"] == "item" and domicile["source"] == "document"
        assert domicile["source_language"] == "roman_ur"
        assert domicile["display"] == "Sindh, urban"  # codes shown as English labels
        education = _entry(view, "education")
        assert education["document"] == {"file_id": f.id, "page": 3, "filename": "domicile_certificate.pdf"}
        assert education["badge"] == "From document" and education["kind"] == "record"
        assert domicile in view["details"]["money_and_place"]["entries"]
        assert education in view["details"]["education"]["entries"]

        # The file is gone: the link goes, the value stays.
        f.status = "deleted"
        db.commit()
        view = VaultView(db).build(ws)
        assert _entry(view, "domicile")["document"] is None
        assert _entry(view, "domicile")["value"] == {"province": "sindh", "area": "urban"}


def test_quote_never_in_view():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        f = _file(db, ws)
        _item(db, ws, "domicile", {"province": "sindh"}, source_type="document", level="shown",
              evidence={**DOC, "file_id": f.id})
        _item(db, ws, "domicile", {"province": "punjab"}, source_type="user_explicit",
              evidence={"quote": SECRET, "source_language": "roman_ur"})
        _item(db, ws, "interest", {"text": "Robotics"})
        _item(db, ws, "interest", {"text": "Robotics"})  # a corroboration carrying the quote
        vault = VaultService(db)
        vault.apply_fact(ws, "identity.full_name", "Ali Khan", "conversation", evidence={"quote": SECRET})
        vault.apply_fact(ws, "identity.full_name", "Ali Raza", "document", evidence={**DOC, "file_id": f.id})
        db.commit()
        view = VaultView(db).build(ws)
        assert view["conflicts"]  # the name card carries both quotes in its evidence
        text = json.dumps(view, default=str)
        assert "SECRET-QUOTE" not in text
        assert '"quote"' not in text
        assert all("quote" not in e for e in VaultView(db).entries_for_document(ws, f.id))


def test_ocr_values_need_confirmation():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        f = _file(db, ws, "photo.jpg")
        ocr = {**DOC, "file_id": f.id, "ocr": True}
        _item(db, ws, "domicile", {"province": "sindh"}, source_type="document", level="inferred", evidence=ocr)
        VaultService(db).apply_fact(ws, "identity.full_name", "Ali Khan", "document", evidence=ocr)
        StudentRecordService(db).apply(
            ws, "education", {"qualification_name": "hssc"}, source_type="document",
            claim_origin="institution_document", capture_method="document_extraction", evidence=ocr,
            verification_status="extracted")
        db.commit()
        view = VaultView(db).build(ws)
        for key in ("domicile", "identity.full_name", "education"):
            entry = _entry(view, key)
            assert entry["level"] == "inferred", key
            assert entry["badge"] == "PAI's guess", key
            assert entry["document"]["file_id"] == f.id, key  # still opens the photo


def test_student_edit_keeps_document_disagreement_visible():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        f = _file(db, ws, "domicile.pdf")
        _item(db, ws, "domicile", {"province": "sindh"}, source_type="document", level="shown",
              evidence={**DOC, "file_id": f.id, "page": 1})
        _item(db, ws, "domicile", {"province": "punjab"}, source_type="user_explicit")
        db.commit()
        entry = _entry(VaultView(db).build(ws), "domicile")
        assert entry["value"] == {"province": "punjab"} and entry["badge"] == "Stated"
        assert entry["disagreements"] == [{
            "value": {"province": "sindh"}, "display": "Sindh", "source": "document",
            "document": {"file_id": f.id, "page": 1, "filename": "domicile.pdf"}}]

        # A second edit by the student does not hide the document's reading.
        _item(db, ws, "domicile", {"province": "balochistan"}, source_type="user_explicit")
        db.commit()
        entry = _entry(VaultView(db).build(ws), "domicile")
        assert entry["value"] == {"province": "balochistan"}
        assert [d["value"] for d in entry["disagreements"]] == [{"province": "sindh"}]
        # Settling on the document's value ends the disagreement.
        _item(db, ws, "domicile", {"province": "sindh"}, source_type="user_explicit")
        db.commit()
        assert _entry(VaultView(db).build(ws), "domicile")["disagreements"] == []


def test_student_edit_over_document_fact_and_record_keeps_disagreement():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        f = _file(db, ws, "cnic.pdf")
        doc = {**DOC, "file_id": f.id, "authority": "government_issued", "locator": "p1"}
        vault = VaultService(db)
        vault.apply_fact(ws, "identity.full_name", "Ali Khan", "document", evidence=doc)
        vault.apply_fact(ws, "identity.full_name", "Muhammad Ali Khan", "user_explicit",
                         evidence={"quote": "my name is Muhammad Ali Khan"})
        records = StudentRecordService(db)
        row = records.apply(ws, "education", {"qualification_name": "hssc", "institution_name": "BISE Lahore"},
                            source_type="document", claim_origin="institution_document",
                            capture_method="document_extraction", evidence=doc,
                            verification_status="document_supported")
        records.apply(ws, "education", {"institution_name": "BISE Rawalpindi"}, source_type="user_explicit",
                      claim_origin="student", capture_method="explicit_correction", record_id=row.id,
                      evidence={"quote": "it was Rawalpindi board"})
        db.commit()
        view = VaultView(db).build(ws)
        link = {"file_id": f.id, "page": 1, "filename": "cnic.pdf"}
        name = _entry(view, "identity.full_name")
        assert name["value"] == "Muhammad Ali Khan" and name["badge"] == "Stated"
        assert name["disagreements"] == [
            {"value": "Ali Khan", "display": "Ali Khan", "source": "document", "document": link}]
        education = _entry(view, "education")
        assert education["value"]["institution_name"] == "BISE Rawalpindi"
        assert [(d["value"], d["document"]) for d in education["disagreements"]] == [
            ({"institution_name": "BISE Lahore"}, link)]

        # Editing back to what the document says ends the disagreement.
        vault.apply_fact(ws, "identity.full_name", "Ali Khan", "user_explicit", evidence={"quote": "Ali Khan"})
        db.commit()
        assert _entry(VaultView(db).build(ws), "identity.full_name")["disagreements"] == []


def test_freshness_marks_budget_stale_after_180_days():
    observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        db.add(VaultFact(workspace_id=ws, field_key="finance.budget", value={"value": {"band": "3_6_lakh"}},
                         source_type="conversation", evidence={"quote": "q"}, status="active",
                         valid_from=observed, created_at=observed))
        db.add(StudentGoal(workspace_id=ws, goal_type="career", title="Become an engineer",
                           source_type="conversation", claim_origin="student", capture_method="chat",
                           status="active", created_at=observed, updated_at=observed))
        StudentRecordService(db).apply(
            ws, "education", {"qualification_name": "matric"}, source_type="conversation",
            claim_origin="student", capture_method="conversation_extraction", evidence={"quote": "q"})
        db.commit()
        education = StudentRecordService(db).list(ws, "education")[0]
        education.created_at = education.updated_at = observed
        db.commit()

        early = VaultView(db).build(ws, now=observed + timedelta(days=179))
        budget = _entry(early, "finance.budget")
        assert budget["stale"] is False
        assert budget["fresh_until"].startswith("2026-06-30")
        assert budget["display"] == "3-6 lakh"
        assert [e["type"] for e in early["stale"]] == ["goal"]  # goals: 90 days

        late = VaultView(db).build(ws, now=observed + timedelta(days=181))
        assert _entry(late, "finance.budget")["stale"] is True
        marks = _entry(late, "education")
        assert marks["fresh_until"] is None and marks["stale"] is False  # marks never go stale
        assert sorted(e["type"] for e in late["stale"]) == ["finance.budget", "goal"]


def test_conflict_card_has_four_answers():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "domicile", {"province": "sindh"})
        write = _item(db, ws, "domicile", {"province": "punjab"})
        assert write.issue_id
        f = _file(db, ws, "someone_else.pdf")
        owner = ProfileIssue(workspace_id=ws, issue_type="document_owner", severity="blocking",
                             affected_type="document", affected_id=f.id, summary="x",
                             clarification_question="Is this your document?",
                             evidence={"file_id": f.id, "filename": f.filename,
                                       "document_names": ["Ali Khan"], "vault_names": ["Sara Ahmed"]})
        db.add(owner)
        db.commit()
        view = VaultView(db).build(ws)
        cards = {c["id"]: c for c in view["conflicts"]}
        card = cards[write.issue_id]
        assert card["answers"] == ["keep_current", "accept_proposed", "both_true", "provide_new"]
        assert card["current"] == {"province": "sindh"} and card["proposed"] == {"province": "punjab"}
        assert card["summary"] and card["question"] and "domicile" in card["question"].lower()
        assert card["type"] == "domicile"
        # Owner cards offer only the answers that work there.
        assert cards[owner.id]["answers"] == ["keep_current", "accept_proposed"]
        assert "someone_else.pdf" in cards[owner.id]["question"]
        entry = _entry(view, "domicile")
        assert entry["in_question"] is True and entry["badge"] == "In question"
        # Sensitive cards stay out of a view without sensitive entries.
        assert VaultView(db).build(ws, include_sensitive=False)["conflicts"] == []


def test_entries_for_document():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        f, other = _file(db, ws, "card.pdf"), _file(db, ws, "other.pdf")
        _item(db, ws, "domicile", {"province": "sindh"}, source_type="document", level="shown",
              evidence={**DOC, "file_id": f.id})
        _item(db, ws, "quota", {"kind": "sports"}, source_type="document", level="shown",
              evidence={**DOC, "file_id": other.id})
        _item(db, ws, "interest", {"text": "Robotics"})
        VaultService(db).apply_fact(ws, "identity.full_name", "Ali Khan", "document",
                                    evidence={**DOC, "file_id": f.id})
        StudentRecordService(db).apply(
            ws, "document", {"file_id": f.id, "document_type": "result_card"}, source_type="document",
            claim_origin="institution_document", capture_method="document_extraction",
            evidence={"file_id": f.id, "authority": "institution_issued"})
        db.commit()
        entries = VaultView(db).entries_for_document(ws, f.id)
        assert sorted(e["type"] for e in entries) == ["domicile", "identity.full_name"]
        assert all(e["document"]["filename"] == "card.pdf" for e in entries)
        documents = VaultView(db).build(ws)["details"]["documents"]["entries"]
        assert [d["value"]["file_id"] for d in documents] == [f.id]


def test_sections_story_and_sensitivity():
    catalog = vault_catalog()
    sections = [s["key"] for s in view_copy()["sections"]]
    assert sections == ["about", "education", "tests", "money_and_place", "documents"]
    assert all(t.section in sections for t in catalog.types(shown_on="details"))
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "interest", {"text": "Robotics"})
        _item(db, ws, "interest", {"text": "Chess"})
        _item(db, ws, "family_member", {"relation": "father", "occupation": "farmer"})
        VaultService(db).apply_fact(ws, "identity.passport_number", "AB1234567", "user_explicit",
                                    evidence={"quote": "q"})
        db.commit()
        view = VaultView(db).build(ws)
        assert list(view["details"]) == sections
        story = {c["type"]: c for c in view["story"]}
        assert set(story) == {t.key for t in catalog.types(shown_on="story")}
        assert story["interest"]["label"] == "Interest" and len(story["interest"]["entries"]) == 2
        assert story["interest"]["rich"] is True and story["value"]["rich"] is False
        assert set(story["interest"]) == {"type", "label", "entries", "rich", "next_step"}
        assert _entry(view, "identity.passport_number")  # the student sees everything
        counselor = VaultView(db).build(ws, include_sensitive=False)
        assert _entries(counselor, "identity.passport_number") == []
        assert _entries(counselor, "family_member") == []
        assert len(_entries(counselor, "interest")) == 2
