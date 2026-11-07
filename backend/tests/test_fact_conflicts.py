"""P1-T8 Task 4 (R-21): the Vault's side of "which is right", on its own (SQLite, no PAI OS). An open Vault card on a mark
or a test score becomes one FactConflictsV1 entry per differing fact key, and the student's answer is written through the
card's own resolution. Fictional student and marks."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import MemoryCandidate, OsOutbox, ProfileIssue, VaultVersion
from app.os.contracts.fact_conflicts import FactConflictsV1
from app.pai_c.connect import fact_conflicts
from app.pai_c.memory import MemoryService
from scripts.counselor_eval_support import StudentSession
from tests.test_document_facts import (add_file, document_candidate, education, proposal, reconcile_all, stated)
from app import pai_c  # noqa: F401

pytestmark = pytest.mark.req("R-21")

GPA = "education.bachelor.gpa"
MARKS = "education.intermediate.marks_obtained"


@pytest.fixture
def student():
    with StudentSession() as s:
        yield s


def bachelor(db, ws, gpa=3.4):
    return stated(db, ws, "BS", institution_name="A Uni", academic_status="completed",
                  result={"gpa": gpa, "gpa_scale": 4})


def transcript_says(db, student, gpa, key="fact_proposal:7:1"):
    """A confirmed OS transcript proposes `gpa`; the Vault reconciles it (a card opens when it differs)."""
    from app.pai_c.connect import document_facts

    outcome, ids = document_facts.apply(db, proposal(student, add_file(db, student.workspace_id), [
        {"key": GPA, "value": gpa}], key=key, doc_type="transcript"))
    db.commit()
    assert outcome == "written"
    return reconcile_all(db, ids)


def built(db, ws) -> dict:
    return FactConflictsV1.model_validate(fact_conflicts.build(db, ws)).model_dump(mode="json")


def only(db, ws) -> dict:
    (entry,) = built(db, ws)["conflicts"]
    return entry


def test_document_vs_vault_card_becomes_one_conflict_per_key(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        (result,) = transcript_says(db, student, 3.2)
        assert result.outcome == "needs_review"
        doc = built(db, ws)
        assert doc["student_ref"] == ws and len(doc["conflicts"]) == 1
        entry = doc["conflicts"][0]
        issue = db.scalar(select(ProfileIssue))
        assert (entry["ref"], entry["key"]) == (f"profile_issue:{issue.id}", GPA)
        assert entry["answers"] == ["keep_current", "accept_proposed", "provide_new"]  # both_true is not asked in the OS
        current, proposed = sorted(entry["values"], key=lambda v: v["side"])
        assert (current["side"], current["value"], current["evidence"], current["document_ref"]) == (
            "current", 3.4, "stated", None)  # said in the chat
        file_id = db.get(MemoryCandidate, issue.candidate_id).evidence["file_id"]
        assert (proposed["value"], proposed["evidence"], proposed["document_ref"]) == (3.2, "shown", file_id)
        assert current["as_of"] and proposed["as_of"]


def test_one_entry_per_differing_key_and_none_for_equal_ones(student):
    from app.pai_c.connect import document_facts

    with student.factory() as db:
        ws = student.workspace_id
        stated(db, ws, "BS", institution_name="A Uni", academic_status="completed",
               result={"gpa": 3.4, "gpa_scale": 4})
        outcome, ids = document_facts.apply(db, proposal(student, add_file(db, ws), [
            {"key": GPA, "value": 3.2}, {"key": "education.bachelor.gpa_scale", "value": 4}], doc_type="transcript"))
        db.commit()
        reconcile_all(db, ids)
        keys = [c["key"] for c in built(db, ws)["conflicts"]]
        assert keys == [GPA]  # the scale is the same on both sides: no question about it


def test_chat_correction_against_a_shown_record_is_a_conflict(student):
    """Ruling problems 5: the student says another number in the chat than the document shows."""
    with student.factory() as db:
        ws = student.workspace_id
        file_id = add_file(db, ws)
        document_candidate(db, ws, file_id, {"marks_obtained": 900, "marks_total": 1100})
        record_id = education(db, ws)[0]["id"]
        said = MemoryCandidateService(db).propose(
            ws, "student_record", key="education", proposed_value={"result": {"marks_obtained": 850}}, confidence=0.9,
            source_type="conversation", input_channel="conversation", entities={"record_id": record_id},
            evidence={"quote": "I got 850"})
        assert MemoryReconciler(db).reconcile(said).outcome == "needs_review"
        db.commit()
        entry = only(db, ws)
        current, proposed = sorted(entry["values"], key=lambda v: v["side"])
        assert entry["key"] == MARKS
        assert (current["value"], current["evidence"], current["document_ref"]) == (900, "shown", file_id)
        assert (proposed["value"], proposed["evidence"], proposed["document_ref"]) == (850, "stated", None)


def test_profile_page_edit_is_not_a_conflict(student):
    """The student's own explicit edit wins by the Vault's rule: no card, so nothing to ask (Ruling problems 5)."""
    with student.factory() as db:
        ws = student.workspace_id
        document_candidate(db, ws, add_file(db, ws), {"marks_obtained": 900, "marks_total": 1100})
        record_id = education(db, ws)[0]["id"]
        edit = MemoryCandidateService(db).propose(
            ws, "student_record", key="education", proposed_value={"result": {"marks_obtained": 910}}, confidence=1.0,
            source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            entities={"record_id": record_id}, evidence={"quote": "q", "capture": "details"})
        assert MemoryReconciler(db).reconcile(edit).accepted
        db.commit()
        assert db.scalars(select(ProfileIssue)).all() == []
        assert built(db, ws)["conflicts"] == []


def test_name_cards_never_cross(student):
    """A document-owner card, an identity card and an entity question give no entry, even when open."""
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws)
        for kwargs in (
            {"issue_type": "document_owner", "affected_type": "document", "summary": "owner",
             "evidence": {"file_id": "f", "vault_names": ["Ali Raza"], "document_names": ["Omar Khan"]}},
            {"issue_type": "conflicting_record", "affected_type": "identity", "summary": "name",
             "conflict_kind": "value_conflict",
             "evidence": {"record_type": "identity", "current": {"full_name": "Ali Raza"},
                          "proposed": {"full_name": "Ali R."}}},
            {"issue_type": "conflicting_record", "affected_type": "education", "summary": "ambiguity",
             "conflict_kind": "entity_ambiguity",
             "evidence": {"record_type": "education", "proposed": {"result": {"gpa": 2}}}},
        ):
            db.add(ProfileIssue(workspace_id=ws, severity="blocking", **kwargs))
        db.commit()
        assert built(db, ws)["conflicts"] == []


def test_a_card_on_another_record_than_the_one_the_facts_stand_for_gives_no_entry(student):
    with student.factory() as db:
        ws = student.workspace_id
        old = bachelor(db, ws)
        db.add(ProfileIssue(
            workspace_id=ws, issue_type="conflicting_record", affected_type="education", affected_id=str(uuid.uuid4()),
            conflict_kind="value_conflict", severity="blocking", summary="s",
            evidence={"record_type": "education", "record_id": str(uuid.uuid4()),
                      "current": {"result": {"gpa": 3.4}}, "proposed": {"result": {"gpa": 3.0}}}))
        db.commit()
        assert old and built(db, ws)["conflicts"] == []


def test_a_test_score_card_is_one_entry(student):
    """A test score read from a document, then another number said in the chat for that same attempt."""
    from app.pai_c.connect import document_facts

    with student.factory() as db:
        ws = student.workspace_id
        file_id = add_file(db, ws)
        outcome, ids = document_facts.apply(db, proposal(student, file_id, [
            {"key": "test.ielts.score", "value": 6.5}], doc_type="ielts_trf"))
        db.commit()
        assert reconcile_all(db, ids)[0].accepted
        (attempt,) = MemoryService(db).profile(ws).records["test_attempt"]
        said = MemoryCandidateService(db).propose(
            ws, "student_record", key="test_attempt", proposed_value={"overall_score": 7.0}, confidence=0.9,
            source_type="conversation", input_channel="conversation", entities={"record_id": attempt["id"]},
            evidence={"quote": "I got 7"})
        assert MemoryReconciler(db).reconcile(said).outcome == "needs_review"
        db.commit()
        entry = only(db, ws)
        assert entry["key"] == "test.ielts.score"
        current, proposed = sorted(entry["values"], key=lambda v: v["side"])
        assert (current["value"], current["evidence"], current["document_ref"]) == (6.5, "shown", file_id)
        assert (proposed["value"], proposed["evidence"]) == (7.0, "stated")
        assert fact_conflicts.answer(db, ws, entry["ref"], entry["key"], "new", "7.5") == {"status": "resolved"}
        (attempt,) = MemoryService(db).profile(ws).records["test_attempt"]
        assert float(attempt["overall_score"]) == 7.5


def test_the_oldest_card_of_a_key_stands(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws)
        transcript_says(db, student, 3.2, key="fact_proposal:7:1")
        first = db.scalar(select(ProfileIssue))
        transcript_says(db, student, 3.0, key="fact_proposal:8:1")
        assert len(db.scalars(select(ProfileIssue)).all()) == 2
        entry = only(db, ws)
        assert entry["ref"] == f"profile_issue:{first.id}"


# ---- the answer ----


def written(db):
    """The candidates an OS answer wrote, oldest first."""
    db.expire_all()
    return [c for c in db.scalars(select(MemoryCandidate).order_by(MemoryCandidate.created_at))
            if (c.evidence or {}).get("capture") == "os_which_is_right"]


def test_answer_proposed_writes_only_that_value_as_the_students_own(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        assert fact_conflicts.answer(db, ws, entry["ref"], GPA, "proposed", request_id=41) == {"status": "resolved"}
        db.commit()
        issue = db.get(ProfileIssue, entry["ref"].partition(":")[2])
        assert issue.status == "resolved" and issue.resolution["action"] == "answered_by_value"
        assert issue.resolution["answers"] == {GPA: {"choice": "proposed", "field": "gpa", "value": 3.2, "request_id": 41}}
        (candidate,) = written(db)
        assert candidate.source_type == "user_explicit" and candidate.evidence["profile_issue_id"] == issue.id
        assert candidate.evidence["os_request_id"] == 41 and candidate.evidence["quote"]  # M4
        assert candidate.proposed_value["value"] == {"result": {"gpa": 3.2}}  # nothing but the value chosen
        (row,) = education(db, ws)
        assert row["result"]["gpa"] == 3.2 and row["evidence_level"] == "stated"
        assert built(db, ws)["conflicts"] == []


def test_answer_current_keeps_the_vault_value_and_writes_nothing(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        before = db.scalar(select(MemoryCandidate.id).order_by(MemoryCandidate.created_at.desc()))
        assert fact_conflicts.answer(db, ws, entry["ref"], GPA, "current") == {"status": "resolved"}
        db.commit()
        issue = db.get(ProfileIssue, entry["ref"].partition(":")[2])
        assert issue.status == "resolved" and issue.resolution["answers"] == {
            GPA: {"choice": "current", "field": "gpa", "value": 3.4}}
        assert written(db) == []
        assert education(db, ws)[0]["result"]["gpa"] == 3.4
        assert db.scalar(select(MemoryCandidate.id).order_by(MemoryCandidate.created_at.desc())) == before
        assert built(db, ws)["conflicts"] == []


@pytest.mark.parametrize("typed,stored", [(3.3, 3.3), ("3.35", 3.35)])
def test_answer_new_writes_the_typed_value_for_that_fact_only(student, typed, stored):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        assert fact_conflicts.answer(db, ws, entry["ref"], GPA, "new", typed) == {"status": "resolved"}
        db.commit()
        issue = db.get(ProfileIssue, entry["ref"].partition(":")[2])
        assert issue.status == "resolved" and issue.resolution["answers"][GPA]["choice"] == "new"
        (candidate,) = written(db)
        assert candidate.proposed_value["value"] == {"result": {"gpa": stored}}
        (row,) = education(db, ws)
        assert row["result"] == {"gpa": stored, "gpa_scale": 4}  # the scale was not touched


TOTAL = "education.intermediate.marks_total"


def two_differences(db, student, obtained=760, total=1050):
    """Saved: 800 of 1100, said by the student. A certificate then reads `obtained` of `total`: one card, two keys."""
    from app.pai_c.connect import document_facts

    ws = student.workspace_id
    stated(db, ws, "FSc", institution_name="A College", result={"marks_obtained": 800, "marks_total": 1100})
    outcome, ids = document_facts.apply(db, proposal(student, add_file(db, ws), [
        {"key": MARKS, "value": obtained}, {"key": TOTAL, "value": total}], doc_type="hssc_certificate"))
    db.commit()
    assert outcome == "written"
    reconcile_all(db, ids)
    return {c["key"]: c for c in built(db, ws)["conflicts"]}


def test_one_card_with_two_differing_values_is_two_entries_answered_one_at_a_time(student):
    """Owner ruling (P1-T8, 2026-11-07): each answer saves only that value; the card stays open until every differing
    value has an answer; nothing is saved that the student did not choose."""
    with student.factory() as db:
        ws = student.workspace_id
        found = two_differences(db, student)
        assert set(found) == {MARKS, TOTAL} and found[MARKS]["ref"] == found[TOTAL]["ref"]
        ref = found[MARKS]["ref"]
        assert fact_conflicts.answer(db, ws, ref, MARKS, "proposed", request_id=5) == {"status": "resolved"}
        db.commit()
        (row,) = education(db, ws)
        assert row["result"] == {"marks_obtained": 760, "marks_total": 1100}  # the total is untouched
        assert db.get(ProfileIssue, ref.partition(":")[2]).status == "open"
        left = built(db, ws)["conflicts"]
        assert [c["key"] for c in left] == [TOTAL]  # the answered key is no longer asked, the other stays
        (candidate,) = written(db)
        assert candidate.proposed_value["value"] == {"result": {"marks_obtained": 760}}
        assert candidate.evidence["os_request_id"] == 5
        # the second answer closes the card: the total stays as it is
        assert fact_conflicts.answer(db, ws, ref, TOTAL, "current", request_id=6) == {"status": "resolved"}
        db.commit()
        issue = db.get(ProfileIssue, ref.partition(":")[2])
        assert issue.status == "resolved" and built(db, ws)["conflicts"] == []
        assert issue.resolution["answers"] == {
            MARKS: {"choice": "proposed", "field": "marks_obtained", "value": 760, "request_id": 5},
            TOTAL: {"choice": "current", "field": "marks_total", "value": 1100, "request_id": 6}}
        assert education(db, ws)[0]["result"] == {"marks_obtained": 760, "marks_total": 1100}
        assert len(written(db)) == 1


def test_new_on_one_value_leaves_the_other_asked(student):
    with student.factory() as db:
        ws = student.workspace_id
        found = two_differences(db, student)
        ref = found[TOTAL]["ref"]
        assert fact_conflicts.answer(db, ws, ref, TOTAL, "new", 1000) == {"status": "resolved"}
        db.commit()
        assert education(db, ws)[0]["result"] == {"marks_obtained": 800, "marks_total": 1000}
        assert db.get(ProfileIssue, ref.partition(":")[2]).status == "open"
        assert [c["key"] for c in built(db, ws)["conflicts"]] == [MARKS]


def test_current_on_one_value_does_not_let_a_later_vault_page_accept_overwrite_it(student):
    """The student kept 1100; answering the other value then closing is not an "accept all" that brings 1050 back."""
    from app.memory.profile_issues import ProfileIssueService

    with student.factory() as db:
        ws = student.workspace_id
        found = two_differences(db, student)
        ref = found[TOTAL]["ref"]
        assert fact_conflicts.answer(db, ws, ref, TOTAL, "current")["status"] == "resolved"
        db.commit()
        assert ProfileIssueService(db).resolve(ws, ref.partition(":")[2], "accept_proposed")["resolved"]
        db.commit()
        assert education(db, ws)[0]["result"] == {"marks_obtained": 760, "marks_total": 1100}


def test_a_close_hook_that_raises_leaves_the_card_closed_and_the_answer_saved(student):
    """Review I2: a hook runs in a savepoint; its failure is logged by class and never undoes the answer."""
    from app.memory import profile_issues

    def broken(db, issue):
        db.execute(select(ProfileIssue.id))  # touches the session, then fails
        raise RuntimeError("hook failed")

    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        profile_issues.register_close_hook(broken)
        try:
            assert fact_conflicts.answer(db, ws, entry["ref"], GPA, "proposed") == {"status": "resolved"}
            db.commit()
        finally:
            profile_issues._CLOSE_HOOKS.remove(broken)
        assert db.get(ProfileIssue, entry["ref"].partition(":")[2]).status == "resolved"
        assert education(db, ws)[0]["result"]["gpa"] == 3.2


def test_an_answer_that_lost_the_race_after_the_lock_does_not_overwrite(student):
    """Review I-c: the other answer lands between the read and the lock; the value it saved stands."""
    from app.memory.profile_issues import ProfileIssueService

    with student.factory() as db:
        ws = student.workspace_id
        found = two_differences(db, student)
        ref = found[MARKS]["ref"]
        real = ProfileIssueService.lock_open

        def lock_after_another_answer(self, workspace_id, issue_id):
            ProfileIssueService.lock_open = real  # the other answer, then our lock
            assert fact_conflicts.answer(db, ws, ref, MARKS, "proposed")["status"] == "resolved"
            return real(self, workspace_id, issue_id)

        with patch.object(ProfileIssueService, "lock_open", lock_after_another_answer):
            assert fact_conflicts.answer(db, ws, ref, MARKS, "new", 790) == {"status": "gone"}
        db.commit()
        assert education(db, ws)[0]["result"]["marks_obtained"] == 760
        assert len(written(db)) == 1


def test_a_hook_whose_version_bump_is_rolled_back_leaves_no_version_and_the_card_closed(student):
    """Review M-1: what a failing hook wrote in its savepoint goes with it; the card still closes."""
    from app.memory import profile_issues
    from app.pai_c.connect import vault_version

    def bump_then_fail(db, issue):
        vault_version.bump(db, issue.workspace_id, [GPA])
        raise RuntimeError("after the bump")

    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        before = db.get(VaultVersion, ws)
        before = before.version if before else None
        profile_issues.register_close_hook(bump_then_fail)
        try:
            assert fact_conflicts.answer(db, ws, entry["ref"], GPA, "current") == {"status": "resolved"}
            db.commit()
        finally:
            profile_issues._CLOSE_HOOKS.remove(bump_then_fail)
        db.expire_all()
        after = db.get(VaultVersion, ws)
        assert (after.version if after else None) == before
        assert db.get(ProfileIssue, entry["ref"].partition(":")[2]).status == "resolved"


def test_refusals_write_nothing(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws, 3.4)
        transcript_says(db, student, 3.2)
        ref = only(db, ws)["ref"]
        codes = [fact_conflicts.answer(db, ws, *args) for args in (
            (ref, GPA, "maybe"), (ref, GPA, "new"), (ref, GPA, "new", "abc"), (ref, GPA, "new", True),
            (ref, "education.bachelor.gpa_scale", "current"),  # not a differing key of this card
            ("profile_issue:" + str(uuid.uuid4()), GPA, "current"), ("finding:1", GPA, "current"),
            (ref, "education.bachelor.level", "new", "x"))]
        assert [c["code"] for c in codes] == ["bad_choice", "new_value_required", "not_typeable", "not_typeable",
                                              "not_a_fact_question", "not_a_fact_question", "not_a_fact_question",
                                              "not_a_fact_question"]
        assert all(c["status"] == "refused" for c in codes)
        assert db.get(ProfileIssue, ref.partition(":")[2]).status == "open"


def test_a_choice_the_card_does_not_offer_is_refused(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        issue = db.get(ProfileIssue, entry["ref"].partition(":")[2])
        with patch("app.pai_c.connect.fact_conflicts._entries",
                   return_value=[{**entry, "answers": ["keep_current"]}]):
            assert fact_conflicts.answer(db, ws, entry["ref"], GPA, "proposed") == {"status": "refused",
                                                                                     "code": "not_offered"}
        assert issue.status == "open"


def test_a_closed_card_is_gone(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws)
        transcript_says(db, student, 3.2)
        ref = only(db, ws)["ref"]
        from app.memory.profile_issues import ProfileIssueService

        ProfileIssueService(db).resolve(ws, ref.partition(":")[2], "keep_current")  # answered on the Vault page
        db.commit()
        assert fact_conflicts.answer(db, ws, ref, GPA, "proposed") == {"status": "gone"}


def test_answer_another_students_card_is_not_a_fact_question(student):
    with student.factory() as db:
        ws = student.workspace_id
        bachelor(db, ws)
        transcript_says(db, student, 3.2)
        ref = only(db, ws)["ref"]
    with StudentSession() as other, other.factory() as db2:
        assert fact_conflicts.answer(db2, other.workspace_id, ref, GPA, "current") == {
            "status": "refused", "code": "not_a_fact_question"}


def test_impossible_value_answer_writes_through_the_reconciler(student):
    """A value above its total: no card, only a new value is taken, written as the student's own edit. (The Vault itself
    refuses such a record, so the OS meets one rarely, e.g. from its own profile values; the path is the same.)"""
    with student.factory() as db:
        ws = student.workspace_id
        stated(db, ws, "FSc", institution_name="A College", result={"marks_obtained": 900, "marks_total": 1100})
        ref = "impossible:" + MARKS
        for choice in ("current", "proposed", "new"):
            assert fact_conflicts.answer(db, ws, ref, MARKS, choice) == {"status": "refused",
                                                                         "code": "new_value_required"}
        assert fact_conflicts.answer(db, ws, "impossible:education.nowhere.marks_obtained",
                                      "education.nowhere.marks_obtained", "new", 900)["code"] == "not_typeable"
        assert fact_conflicts.answer(db, ws, ref, "education.bachelor.gpa", "new", 3)["code"] == "not_typeable"  # key and ref differ
        assert fact_conflicts.answer(db, ws, ref, MARKS, "new", 1200) == {"status": "refused", "code": "invalid_value"}
        db.rollback()  # the bridge rolls back a refusal
        assert fact_conflicts.answer(db, ws, ref, MARKS, "new", 950) == {"status": "resolved"}
        db.commit()
        (row,) = education(db, ws)
        assert row["result"] == {"marks_obtained": 950, "marks_total": 1100}
        candidate = db.scalars(select(MemoryCandidate).order_by(MemoryCandidate.created_at.desc())).first()
        assert candidate.source_type == "user_explicit" and candidate.evidence["capture"] == "os_which_is_right"
        assert candidate.status == "accepted" and candidate.entities == {"record_id": row["id"]}


def test_build_and_answer_make_no_outbox_row_with_the_flag_off(student):
    with student.factory() as db, patch.object(config, "CONNECT_STUDENT_FACTS", False, create=True):
        ws = student.workspace_id
        bachelor(db, ws)
        transcript_says(db, student, 3.2)
        entry = only(db, ws)
        fact_conflicts.answer(db, ws, entry["ref"], GPA, "proposed")
        db.commit()
        assert db.scalars(select(OsOutbox)).all() == [] and db.get(VaultVersion, ws) is None


# ---- the bridge functions and the roadmap's request lines ----


def test_bridge_fact_conflicts_is_none_with_the_flag_off_and_for_a_bad_reference(student):
    from app import pai_os_bridge as bridge

    with student.factory() as db:
        bachelor(db, student.workspace_id)
        transcript_says(db, student, 3.2)
    with patch.object(config, "CONNECT_STUDENT_FACTS", False, create=True):
        assert bridge.fact_conflicts(student.workspace_id) is None
    with patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True):
        assert bridge.fact_conflicts("not-a-uuid") is None
        got = FactConflictsV1.model_validate(bridge.fact_conflicts(student.workspace_id))
        assert [c.key for c in got.conflicts] == [GPA]


def test_bridge_answer_commits_only_a_resolved_answer(student):
    from app import pai_os_bridge as bridge

    with student.factory() as db:
        bachelor(db, student.workspace_id)
        transcript_says(db, student, 3.2)
        ref = only(db, student.workspace_id)["ref"]
    ws = student.workspace_id
    with patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True), patch.object(bridge, "part_on",
                                                                                       return_value=True):
        assert bridge.answer_fact_question("not-a-uuid", ref, GPA, "current") is None
        refused = bridge.answer_fact_question(ws, ref, GPA, "new", "abc")
        assert refused == {"status": "refused", "code": "not_typeable"}
        with student.factory() as db:
            assert db.get(ProfileIssue, ref.partition(":")[2]).status == "open"
        assert bridge.answer_fact_question(ws, ref, GPA, "proposed") == {"status": "resolved"}
        with student.factory() as db:  # committed in the bridge's own session
            assert db.get(ProfileIssue, ref.partition(":")[2]).status == "resolved"
            assert education(db, ws)[0]["result"]["gpa"] == 3.2
    with patch.object(bridge, "part_on", return_value=False):
        assert bridge.answer_fact_question(ws, ref, GPA, "proposed") is None  # the part is off: the OS answers 404


def test_request_texts_are_approved_and_complete(tmp_path):
    from app.pai_c.connect import request_texts

    assert request_texts.line_for("provide", "stated").startswith("PAI needs this from you")
    assert request_texts.line_for("provide", "shown") and request_texts.line_for("provide", "confirmed")
    assert request_texts.line_for("which_is_right") and request_texts.line_for("result_expected")
    assert request_texts.line_for("act") is None and request_texts.line_for("provide", "guess") is None
    bad = tmp_path / "t.yaml"
    bad.write_text("version: 1\napproved: false\ntexts: {}\n")
    with pytest.raises(ValueError, match="not approved"):
        request_texts.load(bad)
    bad.write_text("version: 1\napproved: true\ntexts: {which_is_right: x}\n")
    with pytest.raises(ValueError, match="misses"):
        request_texts.load(bad)
