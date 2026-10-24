# -*- coding: utf-8 -*-
"""Catalog item store: identity, the five-step conflict engine, retraction."""

import pytest
from sqlalchemy import select

from app.memory.errors import MemoryDataError
from app.memory.vault import VaultOutcome
from app.memory.vault_items import VaultItemService
from app.models import ProfileIssue, VaultItem
from scripts.counselor_eval_support import StudentSession


def _apply(svc, ws, item_type, value, *, source_type="conversation", level="stated", **kw):
    evidence = kw.pop("evidence", {"quote": "q", "source_language": "en"})
    return svc.apply(ws, item_type, value, source_type=source_type, level=level, confidence=0.9,
                     evidence=evidence, candidate_id=kw.pop("candidate_id", None), **kw)


def _rows(db, ws, item_type):
    return db.scalars(select(VaultItem).where(VaultItem.workspace_id == ws, VaultItem.item_type == item_type)
                      .order_by(VaultItem.created_at)).all()


def test_same_meaning_merges_evidence():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "interest", {"text": "Robotics"}, level="inferred")
        assert first.outcome == VaultOutcome.CREATED
        again = _apply(svc, ws, "interest", {"text": "  robotics "}, level="stated",
                       evidence={"quote": "I love robotics", "source_language": "en"}, candidate_id="cand-2")
        assert again.outcome == VaultOutcome.CORROBORATED
        assert again.item.id == first.item.id
        assert again.item.level == "stated"  # raised
        corr = again.item.evidence["corroborations"]
        assert corr[-1]["quote"] == "I love robotics" and corr[-1]["candidate_id"] == "cand-2"
        assert "value" not in corr[-1]
        assert len(_rows(db, ws, "interest")) == 1


def test_corroborations_are_capped():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        _apply(svc, ws, "interest", {"text": "Robotics"})
        for _ in range(15):
            last = _apply(svc, ws, "interest", {"text": "Robotics"})
        assert len(last.item.evidence["corroborations"]) == 10


def test_enrich_adds_fields_without_conflict():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "domicile", {"province": "Punjab"})
        out = _apply(svc, ws, "domicile", {"province": "punjab", "area": "rural"})
        assert out.outcome == VaultOutcome.SUPERSEDED and out.issue_id is None
        assert out.item.value == {"province": "Punjab", "area": "rural"}
        assert db.get(VaultItem, first.item.id).status == "superseded"
        assert db.scalar(select(ProfileIssue)) is None


def test_student_edit_wins_and_history_kept():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        doc = _apply(svc, ws, "domicile", {"province": "Sindh"}, source_type="document", level="shown",
                     evidence={"quote": "Domicile: Sindh", "file_id": "f1", "page": 2})
        edit = _apply(svc, ws, "domicile", {"province": "Punjab"}, source_type="user_explicit")
        assert edit.outcome == VaultOutcome.SUPERSEDED
        assert edit.item.value == {"province": "Punjab"} and edit.item.status == "active"
        disagree = edit.item.evidence["disagreements"][0]
        assert disagree["value"] == {"province": "Sindh"} and disagree["file_id"] == "f1"
        assert disagree["page"] == 2 and disagree["source_type"] == "document"
        old = db.get(VaultItem, doc.item.id)
        assert old.status == "superseded" and old.superseded_by == edit.item.id and old.valid_until
        assert [r.id for r in svc.history(ws, edit.item.id)] == [doc.item.id, edit.item.id]
        assert [r.id for r in svc.active(ws, ["domicile"])] == [edit.item.id]


def test_correction_replaces():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "domicile", {"province": "Sindh"})
        out = _apply(svc, ws, "domicile", {"province": "Punjab"}, correction=True)
        assert out.outcome == VaultOutcome.SUPERSEDED and out.issue_id is None
        assert db.get(VaultItem, first.item.id).status == "superseded"
        assert db.scalar(select(ProfileIssue)) is None


def test_temporal_change_replaces_and_keeps_past():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "domicile", {"province": "Sindh"})
        out = _apply(svc, ws, "domicile", {"province": "Punjab"}, temporal=True)
        assert out.outcome == VaultOutcome.SUPERSEDED
        past = db.get(VaultItem, first.item.id)
        assert past.status == "superseded" and past.valid_until is not None
        assert past.value == {"province": "Sindh"}
        assert len(svc.history(ws, out.item.id)) == 2


def test_guess_never_replaces_stated():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        stated = _apply(svc, ws, "certainty", {"score": 7})
        guess = _apply(svc, ws, "certainty", {"score": 3}, level="inferred")
        assert guess.outcome == VaultOutcome.RETAINED
        assert guess.item.id == stated.item.id and guess.item.value == {"score": 7}
        assert len(_rows(db, ws, "certainty")) == 1


def test_latest_wins_rule():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "certainty", {"score": 4, "about": "medicine"})
        out = _apply(svc, ws, "certainty", {"score": 8, "about": "medicine"})
        assert out.outcome == VaultOutcome.SUPERSEDED
        assert out.item.value["score"] == 8
        assert db.get(VaultItem, first.item.id).superseded_by == out.item.id


def test_ask_student_rule_opens_issue():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "domicile", {"province": "Sindh"},
                       evidence={"quote": "main Sindh se hoon", "source_language": "roman_ur"})
        out = _apply(svc, ws, "domicile", {"province": "Punjab"},
                     evidence={"quote": "Punjab ka domicile", "source_language": "roman_ur"})
        assert out.outcome == VaultOutcome.NEEDS_REVIEW and out.item is None
        issue = db.get(ProfileIssue, out.issue_id)
        assert (issue.issue_type, issue.conflict_kind, issue.affected_type) == ("conflict", "vault_item", "vault_item")
        assert issue.affected_id == first.item.id and issue.status == "open"
        assert "Domicile" in issue.clarification_question
        assert "Punjab ka" not in issue.summary and "Sindh se" not in issue.summary
        assert issue.evidence == {"item_type": "domicile", "proposed_value": {"province": "Punjab"},
                                  "current_value": {"province": "Sindh"}}
        assert db.get(VaultItem, first.item.id).conflict_state == "in_question"
        assert len(_rows(db, ws, "domicile")) == 1
        # Confirming the current entry settles the question.
        confirmed = svc.confirm(ws, first.item.id)
        assert confirmed.level == "confirmed" and confirmed.confirmed_at and confirmed.conflict_state == "none"


def test_evidence_wins_document_beats_chat():
    from dataclasses import replace
    from unittest.mock import patch
    from app.memory.catalog import vault_catalog
    real = vault_catalog().type("domicile")
    with StudentSession() as student, student.factory() as db, \
            patch.object(type(vault_catalog()), "type", lambda self, k: replace(real, conflict="evidence_wins")):
        svc, ws = VaultItemService(db), student.workspace_id
        chat = _apply(svc, ws, "domicile", {"province": "Sindh"})
        doc = _apply(svc, ws, "domicile", {"province": "Punjab"}, source_type="document", level="shown")
        assert doc.outcome == VaultOutcome.SUPERSEDED
        assert doc.item.evidence["disagreements"][0]["value"] == {"province": "Sindh"}
        assert db.get(VaultItem, chat.item.id).status == "superseded"
        # Equal rank falls back to asking the student.
        other = _apply(svc, ws, "domicile", {"province": "KP"}, source_type="document", level="shown")
        assert other.outcome == VaultOutcome.NEEDS_REVIEW and other.issue_id


def test_two_brothers_with_names_stay_separate():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        a = _apply(svc, ws, "family_member", {"relation": "brother", "name": "Ali"})
        b = _apply(svc, ws, "family_member", {"relation": "brother", "name": "Omar"})
        assert a.outcome == b.outcome == VaultOutcome.CREATED
        assert a.item.id != b.item.id
        assert len(svc.active(ws, ["family_member"])) == 2


def test_father_said_twice_is_one_entry():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "family_member", {"relation": "father", "occupation": "Farmer"})
        again = _apply(svc, ws, "family_member", {"relation": "Father", "occupation": "farmer"})
        assert again.outcome == VaultOutcome.CORROBORATED and again.item.id == first.item.id
        assert len(svc.active(ws, ["family_member"])) == 1


def test_schema_violation_raises_memory_data_error():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        with pytest.raises(MemoryDataError, match="certainty"):
            _apply(svc, ws, "certainty", {"score": 42})
        with pytest.raises(MemoryDataError, match="interest"):
            _apply(svc, ws, "interest", {"text": "x", "colour": "blue"})
        with pytest.raises(MemoryDataError):
            _apply(svc, ws, "no_such_type", {"text": "x"})


def test_retract_then_was_retracted():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        item = _apply(svc, ws, "interest", {"text": "Cricket"}).item
        assert svc.was_retracted(ws, "interest", {"text": "cricket"}) is False
        gone = svc.retract(ws, item.id, {"reason": "student removed it"})
        assert gone.status == "retracted" and gone.valid_until is not None
        assert svc.active(ws, ["interest"]) == []
        assert svc.was_retracted(ws, "interest", {"text": "cricket"}) is True
        assert svc.was_retracted(ws, "interest", {"text": "Chess"}) is False
        # A document mentioning it again does not bring it back; the student saying it does.
        _apply(svc, ws, "interest", {"text": "Cricket"}, source_type="document", level="shown")
        assert svc.was_retracted(ws, "interest", {"text": "cricket"}) is True
        _apply(svc, ws, "interest", {"text": "Cricket"}, source_type="conversation")
        assert svc.was_retracted(ws, "interest", {"text": "cricket"}) is False


# ---- fix round 1 -----------------------------------------------------------

def test_loose_match_contradiction_keeps_name_and_opens_card():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        ali = _apply(svc, ws, "family_member", {"relation": "brother", "name": "Ali", "occupation": "Doctor"}).item
        out = _apply(svc, ws, "family_member", {"relation": "brother", "occupation": "Engineer"})
        assert out.outcome == VaultOutcome.NEEDS_REVIEW and out.issue_id and out.item is None
        row = db.get(VaultItem, ali.id)
        assert row.status == "active" and row.value["name"] == "Ali" and row.value["occupation"] == "Doctor"
        assert row.conflict_state == "in_question"
        assert len(_rows(db, ws, "family_member")) == 1


def test_unnamed_and_named_contradiction_leaves_original_untouched():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "family_member", {"relation": "brother", "occupation": "Doctor"}).item
        out = _apply(svc, ws, "family_member", {"relation": "brother", "name": "Omar", "occupation": "Engineer"},
                     source_type="user_explicit")
        assert out.outcome == VaultOutcome.NEEDS_REVIEW
        row = db.get(VaultItem, first.id)
        assert row.status == "active" and row.value == {"relation": "brother", "occupation": "Doctor"}


def test_loose_enrich_fills_missing_name():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        _apply(svc, ws, "family_member", {"relation": "father", "occupation": "Farmer"})
        out = _apply(svc, ws, "family_member", {"relation": "father", "name": "Ahmed"})
        assert out.outcome == VaultOutcome.SUPERSEDED
        assert out.item.value == {"relation": "father", "occupation": "Farmer", "name": "Ahmed"}
        assert len(svc.active(ws, ["family_member"])) == 1


def test_history_and_was_retracted_use_exact_identity():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        unnamed = _apply(svc, ws, "family_member", {"relation": "brother"}).item
        svc.retract(ws, unnamed.id, {"reason": "removed"})
        assert svc.was_retracted(ws, "family_member", {"relation": "brother"}) is True
        assert svc.was_retracted(ws, "family_member", {"relation": "brother", "name": "Omar"}) is False
        omar = _apply(svc, ws, "family_member", {"relation": "brother", "name": "Omar"}).item
        assert [r.id for r in svc.history(ws, omar.id)] == [omar.id]


def test_guess_cannot_enrich_a_stated_entry():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "certainty", {"score": 6}).item
        out = _apply(svc, ws, "certainty", {"score": 6, "about": "engineering"}, level="inferred")
        assert out.outcome == VaultOutcome.RETAINED and out.reason == "guess_against_stated"
        row = db.get(VaultItem, first.id)
        assert row.status == "active" and row.value == {"score": 6} and row.level == "stated"


def test_enrich_carries_document_evidence_forward():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        _apply(svc, ws, "domicile", {"province": "Punjab"}, source_type="document", level="shown",
               evidence={"quote": "Domicile: Punjab", "file_id": "f1", "page": 3})
        out = _apply(svc, ws, "domicile", {"province": "Punjab", "area": "rural"},
                     evidence={"quote": "we live in a village", "source_language": "en"}, candidate_id="c9")
        assert out.outcome == VaultOutcome.SUPERSEDED and out.item.level == "shown"
        ev = out.item.evidence
        assert ev["file_id"] == "f1" and ev["page"] == 3 and ev["quote"] == "Domicile: Punjab"
        assert ev["corroborations"][-1]["quote"] == "we live in a village"
        assert ev["corroborations"][-1]["candidate_id"] == "c9"


def test_enrich_never_auto_confirms():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "domicile", {"province": "Punjab"}).item
        svc.confirm(ws, first.id)
        out = _apply(svc, ws, "domicile", {"province": "Punjab", "area": "urban"})
        assert out.item.level == "shown"
        again = _apply(svc, ws, "domicile", {"province": "Punjab", "area": "urban"}, level="confirmed")
        assert again.outcome == VaultOutcome.CORROBORATED and again.item.level == "confirmed"


def _open(db, ws):
    return db.scalars(select(ProfileIssue).where(ProfileIssue.workspace_id == ws,
                                                 ProfileIssue.status == "open")).all()


def test_student_edit_closes_open_card():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        _apply(svc, ws, "domicile", {"province": "Sindh"})
        card = _apply(svc, ws, "domicile", {"province": "KP"})
        assert card.outcome == VaultOutcome.NEEDS_REVIEW and len(_open(db, ws)) == 1
        edit = _apply(svc, ws, "domicile", {"province": "Punjab"}, source_type="user_explicit")
        assert edit.outcome == VaultOutcome.SUPERSEDED and edit.item.value == {"province": "Punjab"}
        assert _open(db, ws) == []
        closed = db.get(ProfileIssue, card.issue_id)
        assert closed.status == "resolved" and closed.resolution["note"] == "superseded" and closed.resolved_at


def test_confirm_and_retract_close_open_card():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        first = _apply(svc, ws, "domicile", {"province": "Sindh"}).item
        _apply(svc, ws, "domicile", {"province": "KP"})
        svc.confirm(ws, first.id)
        assert _open(db, ws) == []
        _apply(svc, ws, "domicile", {"province": "KP"}, source_type="document", level="shown")
        assert len(_open(db, ws)) == 1
        svc.retract(ws, first.id, {"reason": "student removed it"})
        assert _open(db, ws) == []


def test_one_card_at_a_time_per_entry():
    with StudentSession() as student, student.factory() as db:
        svc, ws = VaultItemService(db), student.workspace_id
        _apply(svc, ws, "domicile", {"province": "Sindh"})
        one = _apply(svc, ws, "domicile", {"province": "KP"})
        two = _apply(svc, ws, "domicile", {"province": "Balochistan"})
        assert two.outcome == VaultOutcome.NEEDS_REVIEW and two.issue_id == one.issue_id
        cards = _open(db, ws)
        assert len(cards) == 1 and cards[0].evidence["proposed_value"] == {"province": "Balochistan"}
