"""P1-T7 Task 3 (R-16, row 6.7): the Vault's sink for fact proposals from confirmed PAI OS documents, on its own (SQLite,
no PAI OS). A proposal becomes candidates that the reconciler decides; a repeat does nothing; a file of another
student is refused. Fictional student and marks."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import (BackgroundJob, DocumentArtifact, DocumentProposal, FileRecord, MemoryCandidate, OsOutbox,
                        User, Workspace)
from app.pai_c.connect import document_facts
from app.pai_c.memory import MemoryService
from scripts.counselor_eval_support import StudentSession

pytestmark = pytest.mark.req("R-16")

MARKS = [{"key": "education.intermediate.marks_obtained", "value": 900},
         {"key": "education.intermediate.marks_total", "value": 1100}]


def proposal(student, file_id, facts=MARKS, key="fact_proposal:7:1", doc_type="hssc_certificate", **over):
    return {"schema": "pai.fact_proposal.v1", "key": key, "student_ref": student.workspace_id,
            "document_ref": file_id, "doc_type": doc_type, "confirmed_at": "2026-11-05T09:00:00+00:00",
            "facts": facts, **over}


def add_file(db, workspace_id, status="active"):
    record = FileRecord(workspace_id=workspace_id, filename="hssc.pdf", content_type="application/pdf", size=10,
                        storage_key=f"{workspace_id}/x/hssc.pdf", uploaded_by="human:test", status=status)
    db.add(record)
    db.flush()
    return record.id


def stated(db, ws, name="FSc", **extra):
    candidate = MemoryCandidateService(db).propose(
        ws, "student_record", key="education", proposed_value={"qualification_name": name, **extra}, confidence=0.9,
        source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
        evidence={"quote": "q", "capture": "details"})
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()
    return db.get(MemoryCandidate, candidate.id).result_id


def reconcile_all(db, ids):
    out = [MemoryReconciler(db).reconcile(db.get(MemoryCandidate, i)) for i in ids]
    db.commit()
    return out


def education(db, ws):
    db.expire_all()
    return MemoryService(db).profile(ws).records["education"]


@pytest.fixture
def student():
    with StudentSession() as s:
        yield s


def test_apply_writes_education_result_to_the_chosen_record(student):
    with student.factory() as db:
        ws = student.workspace_id
        record_id = stated(db, ws, institution_name="A College")
        assert education(db, ws)[0]["evidence_level"] == "stated"
        file_id = add_file(db, ws)
        outcome, ids = document_facts.apply(db, proposal(student, file_id))
        db.commit()
        assert outcome == "written" and len(ids) == 1
        candidate = db.get(MemoryCandidate, ids[0])
        assert candidate.entities == {"record_id": record_id}
        assert candidate.proposed_value["value"]["result"] == {"marks_obtained": 900, "marks_total": 1100}
        assert (candidate.source_type, candidate.input_channel) == ("document", "document")
        assert reconcile_all(db, ids)[0].accepted
        (row,) = education(db, ws)
        assert row["id"] == record_id and row["evidence_level"] == "shown"
        assert row["evidence"]["file_id"] == file_id and row["result"]["marks_obtained"] == 900


def test_apply_new_record_uses_the_family_code(student):
    with student.factory() as db:
        ws = student.workspace_id
        outcome, ids = document_facts.apply(db, proposal(student, add_file(db, ws), [
            {"key": "education.matric.marks_obtained", "value": "800"},
            {"key": "education.matric.marks_total", "value": "1050"}], doc_type="ssc_certificate"))
        db.commit()
        assert outcome == "written"
        value = db.get(MemoryCandidate, ids[0]).proposed_value["value"]
        assert value == {"qualification_name": "matric", "result": {"marks_obtained": 800, "marks_total": 1050}}
        assert db.get(MemoryCandidate, ids[0]).entities is None
        assert reconcile_all(db, ids)[0].accepted
        assert education(db, ws)[0]["result"]["marks_total"] == 1050


def test_apply_test_score_to_test_attempt(student):
    with student.factory() as db:
        ws = student.workspace_id
        outcome, ids = document_facts.apply(db, proposal(student, add_file(db, ws), [
            {"key": "test.ielts.score", "value": 6.5}], doc_type="ielts_trf"))
        db.commit()
        assert outcome == "written"
        candidate = db.get(MemoryCandidate, ids[0])
        assert (candidate.key, candidate.proposed_value["value"]) == ("test_attempt",
                                                                      {"test_type": "ielts", "overall_score": 6.5})
        assert candidate.evidence["authority"] == "test_provider_issued"
        assert reconcile_all(db, ids)[0].accepted
        (row,) = MemoryService(db).profile(ws).records["test_attempt"]
        assert float(row["overall_score"]) == 6.5 and row["evidence_level"] == "shown"


def test_repeat_delivery_is_duplicate_no_new_candidates(student):
    with student.factory() as db:
        ws = student.workspace_id
        file_id = add_file(db, ws)
        first = document_facts.apply(db, proposal(student, file_id))
        db.commit()
        again = document_facts.apply(db, proposal(student, file_id))
        db.commit()
        assert first[0] == "written" and again == ("duplicate", first[1])
        assert len(db.scalars(select(MemoryCandidate)).all()) == 1
        assert len(db.scalars(select(DocumentProposal)).all()) == 1
        jobs = [j for j in db.scalars(select(BackgroundJob)).all() if j.job_type == "memory.reconcile"]
        assert len(jobs) == 1 and jobs[0].payload == {"candidate_ids": first[1]}  # no chat notice: no document_file_id


def test_file_of_another_workspace_is_refused(student):
    with student.factory() as db:
        neighbour = User(email="other-student@example.test", username="other_student")
        db.add(neighbour)
        db.flush()
        other = Workspace(name="Other student", owner_user_id=neighbour.id, password_hash="synthetic-test-only")
        db.add(other)
        db.flush()
        theirs = add_file(db, str(other.id))
        trashed = add_file(db, student.workspace_id, status="deleted")
        for ref in (theirs, trashed, str(uuid.uuid4())):
            assert document_facts.apply(db, proposal(student, ref, key=f"k:{ref}")) == ("refused", ["file_not_yours"])
        assert db.scalars(select(MemoryCandidate)).all() == [] and db.scalars(select(DocumentProposal)).all() == []


def test_refusals_no_workspace_and_no_mapping(student):
    with student.factory() as db:
        file_id = add_file(db, student.workspace_id)
        assert document_facts.apply(db, proposal(student, file_id, student_ref=str(uuid.uuid4()))) == (
            "refused", ["no_workspace"])
        assert document_facts.apply(db, proposal(student, file_id, student_ref="not-a-uuid")) == (
            "refused", ["no_workspace"])
        assert document_facts.apply(db, proposal(student, file_id, doc_type="passport")) == ("refused", ["no_mapping"])
        assert document_facts.apply(db, proposal(student, file_id, [{"key": "constraint.budget", "value": "x"},
                                                                    {"key": "education.nowhere.gpa", "value": 3}])
                                    ) == ("refused", ["no_mapping"])
        assert db.scalars(select(MemoryCandidate)).all() == []


def test_os_only_document_is_stated(student):
    with student.factory() as db:
        ws = student.workspace_id
        outcome, ids = document_facts.apply(db, proposal(student, "os:42", key="fact_proposal:42:1"))
        db.commit()
        assert outcome == "written"
        evidence = db.get(MemoryCandidate, ids[0]).evidence
        assert "file_id" not in evidence and evidence["os_document_id"] == 42
        assert reconcile_all(db, ids)[0].accepted
        (row,) = education(db, ws)
        assert row["evidence_level"] == "stated" and row["result"]["marks_obtained"] == 900


def test_accept_raises_vault_version_and_queues_vault_event(student):
    with student.factory() as db, patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True), \
            patch("app.pai_c.connect.outbox.part_on", return_value=True):  # the OS module is on
        ws = student.workspace_id
        stated(db, ws)
        first = db.scalars(select(OsOutbox).where(OsOutbox.kind == "vault_event")).all()
        outcome, ids = document_facts.apply(db, proposal(student, add_file(db, ws)))
        db.commit()
        assert reconcile_all(db, ids)[0].accepted
        rows = db.scalars(select(OsOutbox).where(OsOutbox.kind == "vault_event").order_by(OsOutbox.created_at)).all()
        assert len(first) == 1 and len(rows) == 2
        newest = max(rows, key=lambda r: r.payload["vault_version"])
        assert newest.payload["vault_version"] == 2
        assert "education.intermediate.marks_obtained" in newest.payload["keys"]


def document_candidate(db, ws, file_id, marks, authority="institution_issued"):
    """What the Counsellor's own extraction proposes for the same certificate (a file read before it was typed)."""
    candidate = MemoryCandidateService(db).propose(
        ws, "student_record", key="education", confidence=0.8, source_type="document", input_channel="document",
        proposed_value={"qualification_name": "FSc", "result": marks},
        evidence={"file_id": file_id, "filename": "hssc.pdf", "authority": authority})
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()
    return candidate


def test_same_fact_already_in_the_vault_is_not_a_conflict(student):
    from app.models import ProfileIssue

    with student.factory() as db:
        ws = student.workspace_id
        document_candidate(db, ws, add_file(db, ws), {"marks_obtained": 900, "marks_total": 1100})
        (before,) = education(db, ws)
        assert before["evidence_level"] == "shown"
        outcome, ids = document_facts.apply(db, proposal(student, add_file(db, ws)))
        db.commit()
        (result,) = reconcile_all(db, ids)
        assert outcome == "written" and result.accepted
        assert db.scalars(select(ProfileIssue)).all() == []  # the same fact twice is one fact, not a conflict
        (after,) = education(db, ws)
        assert after["id"] == before["id"] and after["result"] == before["result"]
        assert after["evidence_level"] == "shown"


def test_the_context_line_reflects_the_proposal(student):
    """A typed file skips the Counsellor's reading; once its facts are reconciled the chat's context line counts them."""
    from app.documents.progress import learned_summary

    with student.factory() as db:
        ws = student.workspace_id
        file_id = add_file(db, ws)
        db.add(DocumentArtifact(workspace_id=ws, file_id=file_id, status="ready", document_type="pdf",
                                classification="hssc_certificate", extractor_version="os_document"))
        db.commit()
        artifact = db.scalar(select(DocumentArtifact))
        assert learned_summary(db, artifact) == {"learned": {}, "needs_review": 0}
        _, ids = document_facts.apply(db, proposal(student, file_id))
        db.commit()
        reconcile_all(db, ids)
        db.expire_all()
        assert learned_summary(db, db.scalar(select(DocumentArtifact))) == {"learned": {"education": 1},
                                                                           "needs_review": 0}
