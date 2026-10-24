# -*- coding: utf-8 -*-
"""Cross-task seams the whole-branch review found: one income door, removed
entries that stay removed, fresh rows after the lock, budget follow-ups from
chat, no proposal stuck behind an obsolete card, chat item ids, and re-checks
that refresh freshness."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.memory import extractor
from app.memory.candidates import INCOME_REFUSED, MemoryCandidateService
from app.memory.errors import MemoryDataError
from app.memory.evidence import value_digest
from app.memory.profile_issues import ProfileIssueService
from app.memory.reconciler import MemoryReconciler
from app.memory.student_records import StudentRecordService
from app.memory.vault import VaultService
from app.models import MemoryCandidate, ProfileIssue, VaultDrop, VaultItem
from scripts.counselor_eval_support import StudentSession
from scripts.eval_vault import VaultSession


def _propose(db, ws, ctype, key, value, *, source_type="conversation", quote="q", evidence=None, **kw):
    return MemoryCandidateService(db).propose(
        ws, ctype, key=key, proposed_value=value, confidence=0.9, source_type=source_type,
        evidence={"quote": quote, **(evidence or {})},
        allow_user_explicit=source_type == "user_explicit", **kw)


def _run(db, ws, ctype, key, value, **kw):
    candidate = _propose(db, ws, ctype, key, value, **kw)
    return candidate, MemoryReconciler(db).reconcile(candidate)


def _active(db, ws, item_type):
    return db.scalars(select(VaultItem).where(VaultItem.workspace_id == ws, VaultItem.item_type == item_type,
                                              VaultItem.status == "active")).all()


def _income_drops(s):
    with s.factory() as db:
        return [d.payload for d in db.scalars(select(VaultDrop).where(
            VaultDrop.workspace_id == s.workspace_id, VaultDrop.reason == "household_income"))]


# ---- 1. household income at the single door ---------------------------------


def test_conflict_answer_with_a_salary_is_refused():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        _run(db, ws, "vault_fact", "finance.funding_status", "family pays")
        _run(db, ws, "vault_fact", "finance.funding_status", "scholarship needed")
        db.commit()
        issue = db.scalars(select(ProfileIssue).where(ProfileIssue.workspace_id == ws,
                                                      ProfileIssue.status == "open")).one()
        with pytest.raises(MemoryDataError) as refused:
            ProfileIssueService(db).resolve(ws, issue.id, "provide_new",
                                            value="Father's salary is 80,000 a month, he pays",
                                            capture="vault_api")
        assert str(refused.value) == INCOME_REFUSED
        db.rollback()
        snapshot = VaultService(db).snapshot(ws, include_sensitive=True)
        assert snapshot["finance.funding_status"] == "family pays"
        payloads = _income_drops(s)
        assert payloads == [{"key": "finance.funding_status", "reason": "household_income"}]
        assert "80" not in json.dumps(payloads)


def test_stated_pressure_with_a_salary_is_refused_at_propose():
    with StudentSession() as s, s.factory() as db:
        with pytest.raises(MemoryDataError) as refused:
            _propose(db, s.workspace_id, "vault_item", "pressure",
                     {"text": "Abbu ki tankhwah 50000 hai, fees mushkil", "kind": "money"},
                     source_type="user_explicit", input_channel="profile")
        assert str(refused.value) == INCOME_REFUSED
        db.rollback()
        assert db.scalars(select(MemoryCandidate)).all() == []
        assert _income_drops(s) == [{"key": "pressure", "reason": "household_income"}]


def test_a_study_budget_passes_the_door():
    with StudentSession() as s, s.factory() as db:
        _, result = _run(db, s.workspace_id, "vault_fact", "finance.budget", {"band": "3_6_lakh"},
                         source_type="user_explicit", input_channel="profile",
                         quote="Saal ka 3 se 6 lakh lag sakta hai")
        assert result.accepted
        assert _income_drops(s) == []


# ---- 2. removed facts and records stay removed --------------------------------


def test_removed_fact_is_not_recreated_by_a_document_or_agent():
    doc = {"file_id": "f9", "authority": "government_issued"}
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        assert _run(db, ws, "vault_fact", "location.current_city", "Lahore")[1].accepted
        _, gone = _run(db, ws, "vault_fact", "location.current_city", None, operation="retract",
                       source_type="user_explicit", input_channel="profile")
        assert gone.accepted
        for source, extra in (("document", doc), ("agent", {})):
            candidate, back = _run(db, ws, "vault_fact", "location.current_city", "lahore",
                                   source_type=source, evidence=extra)
            assert not back.accepted and back.reason == "retracted_by_student"
            assert candidate.status == "rejected"
        assert "location.current_city" not in VaultService(db).snapshot(ws)
        # A different city from a document is not what the student removed.
        assert _run(db, ws, "vault_fact", "location.current_city", "Karachi", source_type="document",
                    evidence={**doc, "file_id": "f10"})[1].accepted
        _run(db, ws, "vault_fact", "location.current_city", None, operation="retract",
             source_type="user_explicit", input_channel="profile")
        # The student says it again: it is back, and a document may then agree.
        assert _run(db, ws, "vault_fact", "location.current_city", "Lahore")[1].accepted
        _, agrees = _run(db, ws, "vault_fact", "location.current_city", "Lahore", source_type="document",
                         evidence=doc)
        assert agrees.accepted and agrees.outcome == "corroborated"


def test_removed_record_is_not_recreated_by_an_agent_until_restated():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        _, first = _run(db, ws, "student_record", "skill", {"name": "Python"})
        _, gone = _run(db, ws, "student_record", "skill", None, operation="retract",
                       source_type="user_explicit", input_channel="profile",
                       entities={"record_id": first.result_id})
        assert gone.accepted
        for source, extra in (("agent", {}), ("document", {"file_id": "f1", "authority": "student_authored"})):
            _, back = _run(db, ws, "student_record", "skill", {"name": "python"}, source_type=source,
                           evidence=extra)
            assert not back.accepted and back.reason == "retracted_by_student"
        assert StudentRecordService(db).list(ws, "skill") == []
        assert _run(db, ws, "student_record", "skill", {"name": "Java"}, source_type="agent")[1].accepted
        _, restated = _run(db, ws, "student_record", "skill", {"name": "Python"}, source_type="user_explicit",
                           input_channel="profile")
        assert restated.accepted
        assert _run(db, ws, "student_record", "skill", {"name": "Python"}, source_type="agent")[1].accepted
        assert sorted(r.name for r in StudentRecordService(db).list(ws, "skill")) == ["Java", "Python"]


# ---- 3. fresh rows after the lock ----------------------------------------------


def test_confirm_after_a_concurrent_write_is_refused_and_leaves_one_row():
    with StudentSession() as s:
        ws = s.workspace_id
        with s.factory() as db:
            _, first = _run(db, ws, "vault_item", "certainty", {"score": 4})
            db.commit()
            item_id = first.result_id
        with s.factory() as a, s.factory() as b:
            seen = a.get(VaultItem, item_id)  # the router's lookup, before the lock
            digest = value_digest(seen.value)
            _, chat = _run(b, ws, "vault_item", "certainty", {"score": 8})
            assert chat.accepted
            b.commit()
            _, confirm = _run(a, ws, "vault_item", "certainty", {"score": 4}, source_type="user_explicit",
                              input_channel="profile", entities={"item_id": item_id},
                              evidence={"action": "confirm",
                                        "confirmation": {"value_digest": digest, "confirmed_at": "x"}})
            assert not confirm.accepted and confirm.reason == "value_changed"
            a.commit()
        with s.factory() as db:
            rows = _active(db, ws, "certainty")
            assert [(r.value, r.level) for r in rows] == [({"score": 8}, "stated")]


def test_record_update_after_the_lock_reads_the_current_row():
    edit = dict(source_type="user_explicit", claim_origin="student", capture_method="explicit_correction")
    with StudentSession() as s:
        ws = s.workspace_id
        with s.factory() as db:
            _, first = _run(db, ws, "student_record", "skill", {"name": "Python", "proficiency": "beginner"})
            db.commit()
            record_id = first.result_id
        with s.factory() as a, s.factory() as b:
            StudentRecordService(a).get(ws, "skill", record_id)  # cached before the lock
            StudentRecordService(b).apply(ws, "skill", {"name": "Python 3"}, record_id=record_id, **edit)
            b.commit()
            StudentRecordService(a).apply(ws, "skill", {"proficiency": "advanced"}, record_id=record_id, **edit)
            a.commit()
        with s.factory() as db:
            row = StudentRecordService(db).get(ws, "skill", record_id)
            assert (row.name, row.proficiency) == ("Python 3", "advanced")


# ---- 4. budget follow-ups from chat ---------------------------------------------


def _fake_turns(student, turns, outputs):
    index = {"value": 0}

    async def fake_model(**kwargs):
        assert turns[index["value"]] in kwargs["messages"][0]["content"]
        return json.dumps({"candidates": outputs[index["value"]]})

    return index, fake_model


async def _chat(turns, outputs, check):
    with VaultSession() as student:
        index, fake_model = _fake_turns(student, turns, outputs)
        with patch.object(extractor, "chat_completion", fake_model), \
                patch.object(extractor, "_model_config", return_value=("test", "test", None)):
            for i, text in enumerate(turns):
                index["value"] = i
                student.student_message(text)
                await student.extract_and_reconcile()
        with student.factory() as db:
            return check(student, db)


def _budget(value, quote):
    return {"candidate_type": "vault_fact", "operation": "upsert", "key": "finance.budget",
            "proposed_value": value, "quote": quote, "confidence": 0.9}


@pytest.mark.asyncio
async def test_budget_follow_ups_merge_onto_the_saved_band():
    turns = ["Hum saal ka 3 se 6 lakh de sakte hain", "Sirf fees, hostel nahi",
             "Scholarship ke baghair nahi ho sakta"]
    outputs = [[_budget({"band": "3_6_lakh"}, "3 se 6 lakh")],
               [_budget({"covers": "fees_only"}, "Sirf fees, hostel nahi")],
               [_budget({"possible_without_scholarship": "no"}, "Scholarship ke baghair nahi ho sakta")]]

    def check(student, db):
        assert db.scalars(select(ProfileIssue).where(ProfileIssue.status == "open")).all() == []
        return VaultService(db).snapshot(student.workspace_id, include_sensitive=True)["finance.budget"]

    budget = await _chat(turns, outputs, check)
    assert budget == {"band": "3_6_lakh", "covers": "fees_only", "possible_without_scholarship": "no"}


def test_partial_budget_merges_and_empty_merge_is_still_empty():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        with pytest.raises(MemoryDataError, match="empty_budget"):
            _propose(db, ws, "vault_fact", "finance.budget", {"covers": "fees_only"}, quote="sirf fees")
        db.rollback()
        assert _run(db, ws, "vault_fact", "finance.budget", {"band": "3_6_lakh"}, quote="3 se 6 lakh")[1].accepted
        candidate = _propose(db, ws, "vault_fact", "finance.budget", {"covers": "fees_only"}, quote="sirf fees")
        assert candidate.proposed_value == {"value": {"band": "3_6_lakh", "covers": "fees_only"}}
        # A new amount replaces the saved one instead of sitting beside it.
        replaced = _propose(db, ws, "vault_fact", "finance.budget", {"min": 200000, "max": 300000},
                            quote="2 se 3 lakh")
        assert replaced.proposed_value == {"value": {"min": 200000, "max": 300000}}


@pytest.mark.asyncio
async def test_only_changed_budget_figures_must_be_in_the_students_words():
    turn = SimpleNamespace(user_text="Sirf fees, hostel nahi", user_event_id="evt", records={},
                           vault={"finance.budget": {"min": 300000, "max": 600000, "currency": "PKR"}},
                           existing_memories=[], recent=[], assistant_text="", is_empty=lambda: False)
    candidates = [_budget({"min": 300000, "max": 600000, "covers": "fees_only"}, "Sirf fees"),
                  _budget({"min": 400000, "max": 600000}, "Sirf fees")]
    with patch.object(extractor, "chat_completion", return_value=json.dumps({"candidates": candidates})), \
            patch.object(extractor, "_model_config", return_value=("test", "test", None)):
        out = await extractor.extract_candidates(turn, {"finance.budget"}, [])
    assert [c.proposed_value for c in out.candidates] == [{"min": 300000, "max": 600000, "covers": "fees_only"}]
    assert len(out.drops) == 1 and "min=400000" in out.drops[0]["reason"]


def test_a_guessed_budget_is_never_promoted_by_a_follow_up():
    for source, extra in (("agent", {}), ("conversation", {"inferred": True})):
        with StudentSession() as s, s.factory() as db:
            ws = s.workspace_id
            assert _run(db, ws, "vault_fact", "finance.budget", {"band": "3_6_lakh"}, source_type=source,
                        evidence=extra, quote="3 se 6 lakh")[1].accepted
            db.commit()
            with pytest.raises(MemoryDataError, match="empty_budget"):
                _propose(db, ws, "vault_fact", "finance.budget", {"covers": "fees_only"},
                         quote="sirf fees, hostel nahi")
            db.rollback()
            fact = VaultService(db).get_fact(ws, "finance.budget")
            assert fact.source_type == source and fact.value == {"value": {"band": "3_6_lakh"}}


@pytest.mark.asyncio
async def test_a_guessed_figure_still_needs_the_students_words():
    turn = SimpleNamespace(user_text="Sirf fees, hostel nahi", user_event_id="evt", records={},
                           vault={"finance.budget": {"min": 300000, "max": 600000}},
                           vault_guesses={"finance.budget"},
                           existing_memories=[], recent=[], assistant_text="", is_empty=lambda: False)
    candidates = [_budget({"min": 300000, "max": 600000, "covers": "fees_only"}, "Sirf fees")]
    with patch.object(extractor, "chat_completion", return_value=json.dumps({"candidates": candidates})),             patch.object(extractor, "_model_config", return_value=("test", "test", None)):
        out = await extractor.extract_candidates(turn, {"finance.budget"}, [])
    assert out.candidates == [] and "min=300000" in out.drops[0]["reason"]


def test_turn_context_names_guessed_facts():
    from app.memory.extraction_context import build_turn_context
    with VaultSession() as student:
        ws = student.workspace_id
        with student.factory() as db:
            _run(db, ws, "vault_fact", "finance.budget", {"band": "3_6_lakh"}, source_type="agent")
            _run(db, ws, "vault_fact", "location.current_city", "Lahore")
            db.commit()
        event_id = student.student_message("Sirf fees")
        with student.factory() as db:
            context = build_turn_context(db, ws, event_id)
            assert context.vault_guesses == {"finance.budget"}


# ---- 5. no proposal stuck behind an obsolete card ---------------------------------


def _waiting(db, candidate):
    from app.documents.progress import learned_summary
    artifact = SimpleNamespace(workspace_id=candidate.workspace_id,
                               extraction_summary={"candidate_ids": [candidate.id]})
    return learned_summary(db, artifact)["needs_review"]


def test_student_edit_closes_the_card_and_its_proposal():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        _, first = _run(db, ws, "vault_item", "domicile", {"province": "punjab"})
        doc, _ = _run(db, ws, "vault_item", "domicile", {"province": "balochistan"}, source_type="document",
                      evidence={"file_id": "f1", "authority": "government_issued"})
        assert doc.status == "needs_review" and _waiting(db, doc) == 1
        _, edit = _run(db, ws, "vault_item", "domicile", {"province": "sindh"}, source_type="user_explicit",
                       input_channel="profile", entities={"item_id": first.result_id},
                       evidence={"semantic_correction": True})
        assert edit.accepted
        db.refresh(doc)
        assert doc.status == "rejected" and doc.rejection_reason == "superseded_by_student_edit"
        assert _waiting(db, doc) == 0
        [issue] = db.scalars(select(ProfileIssue).where(ProfileIssue.workspace_id == ws)).all()
        assert issue.status == "resolved" and issue.resolution["action"] == "obsolete"


def test_retract_closes_the_card_and_its_proposal():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        _, first = _run(db, ws, "vault_item", "domicile", {"province": "punjab"})
        chat, _ = _run(db, ws, "vault_item", "domicile", {"province": "sindh"})
        assert chat.status == "needs_review"
        _, gone = _run(db, ws, "vault_item", "domicile", None, operation="retract", source_type="user_explicit",
                       input_channel="profile", entities={"item_id": first.result_id})
        assert gone.accepted
        db.refresh(chat)
        assert chat.status == "rejected" and chat.rejection_reason == "entry_removed"
        assert _waiting(db, chat) == 0


# ---- 8. a chat item id needs a change flag -----------------------------------------


def test_chat_item_id_without_a_change_flag_is_a_new_proposal():
    with StudentSession() as s, s.factory() as db:
        ws = s.workspace_id
        _, robotics = _run(db, ws, "vault_item", "interest", {"text": "Robotics"})
        _, music = _run(db, ws, "vault_item", "interest", {"text": "Music"},
                        entities={"item_id": robotics.result_id})
        assert music.accepted and music.outcome == "created" and music.result_id != robotics.result_id
        assert sorted(i.value["text"] for i in _active(db, ws, "interest")) == ["Music", "Robotics"]
        _, corrected = _run(db, ws, "vault_item", "interest", {"text": "Robotics and drones"},
                            entities={"item_id": robotics.result_id}, evidence={"semantic_correction": True})
        assert corrected.accepted and corrected.outcome == "superseded"
        assert sorted(i.value["text"] for i in _active(db, ws, "interest")) == ["Music", "Robotics and drones"]


# ---- 10. a re-checked entry the student restates is fresh again ---------------------


@pytest.mark.asyncio
async def test_restated_stale_item_is_proposed_again_and_refreshed():
    from datetime import datetime, timedelta, timezone

    from app.memory.extraction_context import vault_items_for_extraction
    from app.memory.vault_view import VaultView

    text = "Haan, abhi bhi wohi, Abbu engineer hi chahte hain"
    with VaultSession() as student:
        ws = student.workspace_id
        with student.factory() as db:
            _, saved = _run(db, ws, "vault_item", "family_member",
                            {"relation": "father", "wish": "Wants the student to become an engineer"})
            old = datetime.now(timezone.utc) - timedelta(days=400)
            item = db.get(VaultItem, saved.result_id)
            item.observed_at = item.created_at = item.valid_from = old
            db.commit()
            assert item.id in [e["id"] for e in VaultView(db).build(ws, include_sensitive=True)["stale"]]
            shown = vault_items_for_extraction(db, ws, text)
            assert [e.get("needs_recheck") for e in shown if e["id"] == item.id] == [True]
            prompt = extractor.build_user_prompt(SimpleNamespace(
                records={}, items=shown, vault={}, existing_memories=[], recent=[], user_text=text,
                assistant_text=""))
            assert '"needs_recheck": true' in prompt
        assert "needs_recheck" in extractor.SYSTEM_PROMPT

        restated = {"candidate_type": "vault_item", "operation": "upsert", "key": "family_member",
                    "proposed_value": {"relation": "father", "wish": "Wants the student to become an engineer"},
                    "quote": "Haan, abhi bhi wohi", "confidence": 0.9}

        async def fake_model(**kwargs):
            return json.dumps({"candidates": [restated]})

        with patch.object(extractor, "chat_completion", fake_model), \
                patch.object(extractor, "_model_config", return_value=("test", "test", None)):
            student.student_message(text)
            await student.extract_and_reconcile()
        with student.factory() as db:
            [row] = _active(db, ws, "family_member")
            assert row.id == item.id  # corroborated, not a second entry
            assert row.evidence["corroborations"][-1]["source_type"] == "conversation"
            assert row.id not in [e["id"] for e in VaultView(db).build(ws, include_sensitive=True)["stale"]]
