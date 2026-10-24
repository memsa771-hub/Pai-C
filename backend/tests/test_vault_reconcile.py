# -*- coding: utf-8 -*-
"""Catalog items and the Vault rules wired into candidate -> reconciler."""

from sqlalchemy import select

from app.memory.candidates import MemoryCandidateService
from app.memory.profile_issues import ProfileIssueService
from app.memory.reconciler import MemoryReconciler
from app.memory.student_records import StudentRecordService
from app.memory.vault import VaultService
from app.models import MemoryCandidate, ProfileIssue, VaultAssertion, VaultItem
from scripts.counselor_eval_support import StudentSession


def _propose(db, ws, candidate_type, key, value, *, source_type="conversation", quote="q",
             evidence=None, **kw):
    return MemoryCandidateService(db).propose(
        ws, candidate_type, key=key, proposed_value=value, confidence=0.9, source_type=source_type,
        evidence={"quote": quote, **(evidence or {})},
        allow_user_explicit=source_type == "user_explicit", **kw)


def _run(db, ws, candidate_type, key, value, **kw):
    candidate = _propose(db, ws, candidate_type, key, value, **kw)
    return candidate, MemoryReconciler(db).reconcile(candidate)


def _items(db, ws, item_type):
    return db.scalars(select(VaultItem).where(VaultItem.workspace_id == ws, VaultItem.item_type == item_type)
                      .order_by(VaultItem.created_at)).all()


def test_vault_item_candidate_round_trip():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        candidate, result = _run(db, ws, "vault_item", "interest", {"text": "Robotics"},
                                 quote="I love robotics")
        assert result.accepted and result.outcome == "created"
        item = db.get(VaultItem, result.result_id)
        assert item.value == {"text": "Robotics"} and item.level == "stated"
        assert item.candidate_id == candidate.id and candidate.status == "accepted"
        assertion = db.scalar(select(VaultAssertion).where(VaultAssertion.candidate_id == candidate.id))
        assert assertion.domain == "story" and assertion.canonical_id == item.id
        # Agreement corroborates the same entry.
        _, again = _run(db, ws, "vault_item", "interest", {"text": "robotics"})
        assert again.accepted and again.outcome == "corroborated" and again.result_id == item.id
        # The student removes it.
        gone, removed = _run(db, ws, "vault_item", "interest", None, operation="retract",
                             source_type="user_explicit", entities={"item_id": item.id})
        assert removed.accepted and gone.status == "accepted"
        assert db.get(VaultItem, item.id).status == "retracted"


def test_inferred_item_level_and_retract_needs_the_student():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, guess = _run(db, ws, "vault_item", "interest", {"text": "Robotics"}, evidence={"inferred": True})
        item = db.get(VaultItem, guess.result_id)
        assert item.level == "inferred"
        agent, refused = _run(db, ws, "vault_item", "interest", None, operation="retract",
                              source_type="agent", entities={"item_id": item.id})
        assert not refused.accepted and agent.status == "rejected"
        assert db.get(VaultItem, item.id).status == "active"


def test_inferred_fact_does_not_replace_stated_fact():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, stated = _run(db, ws, "vault_fact", "preferences.study_mode", "on_campus")
        assert stated.accepted
        guess, result = _run(db, ws, "vault_fact", "preferences.study_mode", "online",
                             evidence={"inferred": True})
        assert not result.accepted and result.outcome == "retained"
        assert result.reason == "guess_against_stated"
        assert guess.status == "rejected" and guess.rejection_reason == "guess_against_stated"
        assert VaultService(db).snapshot(ws)["preferences.study_mode"] == "on_campus"
        # The student's own edit is not a guess, even if marked inferred.
        _, edit = _run(db, ws, "vault_fact", "preferences.study_mode", "hybrid",
                       source_type="user_explicit", evidence={"inferred": True})
        assert edit.accepted


def test_inferred_record_does_not_replace_stated_record():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, stated = _run(db, ws, "student_record", "skill", {"name": "Python", "proficiency": "beginner"})
        assert stated.accepted
        guess, result = _run(db, ws, "student_record", "skill", {"name": "Python", "proficiency": "expert"},
                             evidence={"inferred": True})
        assert not result.accepted and result.outcome == "retained"
        assert result.reason == "guess_against_stated" and guess.status == "rejected"
        assert StudentRecordService(db).list(ws, "skill")[0].proficiency == "beginner"
        assert db.scalar(select(ProfileIssue)) is None


def test_assertion_records_source_language():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        candidate, _ = _run(db, ws, "vault_fact", "preferences.study_mode", "online",
                            quote="mujhe online parhna hai")
        assertion = db.scalar(select(VaultAssertion).where(VaultAssertion.candidate_id == candidate.id))
        assert assertion.language == "roman_ur"


def test_ocr_document_record_is_extracted_not_supported():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        evidence = {"authority": "institution_issued", "file_id": "f-ocr", "ocr": True}
        _, result = _run(db, ws, "student_record", "skill", {"name": "Welding"},
                         source_type="document", evidence=evidence, input_channel="document")
        assert result.accepted
        assert StudentRecordService(db).list(ws, "skill")[0].verification_status == "extracted"
        _, typed = _run(db, ws, "student_record", "skill", {"name": "Drafting"}, source_type="document",
                        evidence={"authority": "institution_issued", "file_id": "f-pdf"},
                        input_channel="document")
        rows = {r.name: r for r in StudentRecordService(db).list(ws, "skill")}
        assert rows["Drafting"].verification_status == "document_supported"
        # An OCR-read item is PAI's reading, not "shown", until the student confirms.
        _, item = _run(db, ws, "vault_item", "domicile", {"province": "Punjab"}, source_type="document",
                       evidence=evidence, input_channel="document")
        assert db.get(VaultItem, item.result_id).level == "inferred"


def test_retracted_item_not_recreated_from_document():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, made = _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        _run(db, ws, "vault_item", "domicile", None, operation="retract", source_type="user_explicit",
             entities={"item_id": made.result_id})
        doc, result = _run(db, ws, "vault_item", "domicile", {"province": "Sindh"}, source_type="document",
                           evidence={"file_id": "f1", "authority": "government_issued"},
                           input_channel="document")
        assert not result.accepted and result.reason == "retracted_by_student"
        assert doc.status == "rejected" and doc.rejection_reason == "retracted_by_student"
        assert [r.status for r in _items(db, ws, "domicile")] == ["retracted"]
        # Only the student saying it again brings it back.
        _, back = _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        assert back.accepted and back.outcome == "created"


def test_newer_proposal_rejects_the_earlier_one():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        first, one = _run(db, ws, "vault_item", "domicile", {"province": "KP"})
        assert one.outcome == "needs_review" and first.status == "needs_review"
        second, two = _run(db, ws, "vault_item", "domicile", {"province": "Balochistan"})
        assert two.outcome == "needs_review" and second.status == "needs_review"
        db.refresh(first)
        assert first.status == "rejected" and first.rejection_reason == "superseded_by_newer_proposal"
        assert db.scalars(select(MemoryCandidate).where(MemoryCandidate.status == "needs_review")).all() == [second]


def test_issue_both_true_keeps_old_as_past():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, old = _run(db, ws, "vault_item", "domicile", {"province": "Sindh"}, source_type="document",
                      evidence={"file_id": "f1", "authority": "government_issued"}, input_channel="document")
        assert db.get(VaultItem, old.result_id).level == "shown"
        proposal, _ = _run(db, ws, "vault_item", "domicile", {"province": "Punjab"})
        issue = db.scalar(select(ProfileIssue).where(ProfileIssue.status == "open"))
        out = ProfileIssueService(db).resolve(ws, issue.id, "both_true")
        assert out["resolved"] and out["action"] == "both_true"
        past = db.get(VaultItem, old.result_id)
        now = db.get(VaultItem, out["id"])
        assert past.status == "superseded" and past.valid_until and past.superseded_by == now.id
        assert now.status == "active" and now.value == {"province": "punjab"}
        assert now.evidence["semantic_temporal_change"] is True
        # A change over time, not a disagreement with the document.
        assert now.evidence["change"] == "temporal" and "disagreements" not in now.evidence
        assert issue.status == "resolved" and issue.resolution["action"] == "both_true"
        assert proposal.status == "superseded"


def test_keep_current_settles_item_in_question():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, old = _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        _run(db, ws, "vault_item", "domicile", {"province": "Punjab"})
        assert db.get(VaultItem, old.result_id).conflict_state == "in_question"
        issue = db.scalar(select(ProfileIssue).where(ProfileIssue.status == "open"))
        ProfileIssueService(db).resolve(ws, issue.id, "keep_current")
        assert db.get(VaultItem, old.result_id).conflict_state == "none"


# ---- fix round 1 -----------------------------------------------------------

def _active(db, ws, item_type):
    return [r.value for r in _items(db, ws, item_type) if r.status == "active"]


def test_change_flags_only_count_from_the_student():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        _, agent = _run(db, ws, "vault_item", "domicile", {"province": "KP"}, source_type="agent",
                        evidence={"semantic_correction": True})
        assert not agent.accepted
        _, ocr = _run(db, ws, "vault_item", "domicile", {"province": "Punjab"}, source_type="document",
                      evidence={"file_id": "f", "authority": "government_issued", "ocr": True,
                                "semantic_temporal_change": True}, input_channel="document")
        assert not ocr.accepted
        assert _active(db, ws, "domicile") == [{"province": "sindh"}]


def test_repeated_proposal_is_a_duplicate():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        a, _ = _run(db, ws, "vault_item", "domicile", {"province": "KP"})
        b, rb = _run(db, ws, "vault_item", "domicile", {"province": "KP"})
        assert not rb.accepted and rb.reason == "duplicate_proposal"
        assert b.status == "rejected" and b.rejection_reason == "duplicate_proposal"
        assert a.status == "needs_review"
        cards = db.scalars(select(ProfileIssue).where(ProfileIssue.status == "open")).all()
        assert len(cards) == 1 and cards[0].candidate_id == a.id
        out = ProfileIssueService(db).resolve(ws, cards[0].id, "accept_proposed")
        assert out["resolved"]
        assert _active(db, ws, "domicile") == [{"province": "kpk"}]


def test_inferred_correction_never_replaces_in_any_engine():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "vault_fact", "preferences.study_mode", "on_campus")
        _, fact = _run(db, ws, "vault_fact", "preferences.study_mode", "online",
                       evidence={"inferred": True, "semantic_correction": True})
        assert fact.outcome == "retained" and fact.reason == "guess_against_stated"
        _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        _, item = _run(db, ws, "vault_item", "domicile", {"province": "KP"},
                       evidence={"inferred": True, "semantic_correction": True})
        assert item.outcome == "retained" and item.reason == "guess_against_stated"
        assert _active(db, ws, "domicile") == [{"province": "sindh"}]


def test_agent_fact_cannot_replace_stated_value():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "vault_fact", "preferences.study_mode", "on_campus")
        _, agent = _run(db, ws, "vault_fact", "preferences.study_mode", "online", source_type="agent")
        assert agent.outcome == "retained" and agent.reason == "guess_against_stated"
        assert VaultService(db).snapshot(ws)["preferences.study_mode"] == "on_campus"
        _run(db, ws, "student_record", "skill", {"name": "Python", "proficiency": "beginner"})
        _, rec = _run(db, ws, "student_record", "skill", {"name": "Python", "proficiency": "expert"},
                      source_type="agent")
        assert rec.outcome == "retained" and rec.reason == "guess_against_stated"


def test_document_backed_guess_record_stops_being_a_guess():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        value = {"name": "Python", "proficiency": "beginner"}
        _, guess = _run(db, ws, "student_record", "skill", value, evidence={"inferred": True})
        assert guess.accepted
        _, doc = _run(db, ws, "student_record", "skill", value, source_type="document",
                      evidence={"file_id": "f1", "authority": "institution_issued"}, input_channel="document")
        assert doc.accepted
        row = StudentRecordService(db).list(ws, "skill")[0]
        assert row.evidence["inferred"] is False
        _, later = _run(db, ws, "student_record", "skill", {"name": "Python", "proficiency": "expert"},
                        evidence={"inferred": True})
        assert later.outcome == "retained" and later.reason == "guess_against_stated"


def test_item_assertion_domain_and_language_for_details_and_story():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        details, _ = _run(db, ws, "vault_item", "domicile", {"province": "Punjab"},
                          quote="mera domicile Punjab ka hai")
        story, _ = _run(db, ws, "vault_item", "interest", {"text": "Robotics"}, quote="I love robotics")
        by = {a.candidate_id: a for a in db.scalars(select(VaultAssertion))}
        assert (by[details.id].domain, by[details.id].language) == ("details", "roman_ur")
        assert (by[story.id].domain, by[story.id].language) == ("story", "en")


# ---- carried from the Task 5 review (N1) ------------------------------------

def test_document_temporal_flag_is_ignored():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "vault_item", "domicile", {"province": "Sindh"})
        _, result = _run(db, ws, "vault_item", "domicile", {"province": "Punjab"}, source_type="document",
                         evidence={"file_id": "f", "authority": "government_issued",
                                   "semantic_temporal_change": True}, input_channel="document")
        rows = _items(db, ws, "domicile")
        assert all((r.evidence or {}).get("change") != "temporal" for r in rows)
        if result.result_id:
            assert (db.get(VaultItem, result.result_id).evidence or {}).get("change") != "temporal"


def test_item_confirm_must_name_the_items_own_type():
    from app.memory.evidence import value_digest
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, created = _run(db, ws, "vault_item", "interest", {"text": "Robotics"}, quote="I love robotics")
        item = db.get(VaultItem, created.result_id)
        evidence = {"action": "confirm", "confirmation": {"value_digest": value_digest(item.value)}}
        _, result = _run(db, ws, "vault_item", "strength", {"text": "Robotics"}, source_type="user_explicit",
                         input_channel="profile", entities={"item_id": item.id}, evidence=evidence)
        assert not result.accepted and result.reason == "wrong_type"
        assert db.get(VaultItem, item.id).level == "stated"
        _, result = _run(db, ws, "vault_item", "interest", {"text": "Robotics"}, source_type="user_explicit",
                         input_channel="profile", entities={"item_id": item.id}, evidence=evidence)
        assert result.accepted and db.get(VaultItem, result.result_id).level == "confirmed"
