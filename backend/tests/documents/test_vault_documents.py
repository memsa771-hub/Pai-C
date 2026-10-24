# -*- coding: utf-8 -*-
"""Documents follow the Vault's rules: photos by OCR, subject marks, drops, owner.

Fake OCR and fake model output only. The real parse, extract and reconcile
jobs run on an isolated SQLite student, so these exercise the production path
from bytes to Vault.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select

from app.documents.handlers import extract_document_job, parse_document_job
from app.documents.ocr import OcrPage, VisionModelOcr
from app.documents.parsers import parse_document
from app.documents.service import DocumentArtifactService
from app.documents.types import detect_document_type
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import (
    BackgroundJob, CourseRecord, FileRecord, MemoryCandidate, ProfileIssue, VaultDrop,
)
from scripts.eval_vault import VaultSession
from tests.documents.test_parse_job import _StubStore

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

RESULT_CARD = (
    "BOARD OF INTERMEDIATE EDUCATION LAHORE\n"
    "RESULT CARD\n"
    "Name: Ali Khan\n"
    "HSSC Pre-Engineering\n"
    "Physics | 85 / 100 | A\n"
    "Chemistry | 78 / 100 | B\n"
    "Total | 920 / 1100"
)


class _FakeOcr:
    """Records exactly what it was sent; never calls a model."""

    name = "fake_ocr"

    def __init__(self, text=RESULT_CARD):
        self.text = text
        self.sent = []

    async def transcribe(self, images):
        self.sent.extend(images)
        return [OcrPage(page_number=number, text=self.text) for number, _ in images]


def _finding(candidate_type, key, value, quote, locator="p1"):
    return {"candidate_type": candidate_type, "key": key, "proposed_value": value,
            "quote": quote, "locator": locator, "confidence": 0.9}


def _upload(student, filename, data, content_type):
    with student.factory() as db:
        record = FileRecord(id=str(uuid.uuid4()), workspace_id=student.workspace_id,
                            filename=filename, content_type=content_type, size=len(data),
                            storage_key=f"test/{filename}", uploaded_by=f"human:{student.user_id}")
        db.add(record)
        db.flush()
        DocumentArtifactService(db).register_and_enqueue(
            student.workspace_id, record.id, data, filename, content_type)
        db.commit()
        return record.id, record.storage_key


def _job(student, file_id, job_type):
    return SimpleNamespace(id=str(uuid.uuid4()), workspace_id=student.workspace_id,
                           payload={"file_id": file_id}, job_type=job_type)


HOLDER = {"value": "Ali Khan", "quote": "Name: Ali Khan", "locator": "p1"}


def _model(findings, classification="transcript", holder=HOLDER):
    async def fake_model(**kwargs):
        return json.dumps({"classification": classification, "classification_confidence": 0.9,
                           "title": "Result card", "holder_name": holder, "findings": findings})
    return fake_model


def _run_jobs(student, db, job_type, handler):
    for job in db.scalars(select(BackgroundJob).where(
            BackgroundJob.workspace_id == student.workspace_id,
            BackgroundJob.job_type == job_type,
            BackgroundJob.status == "pending")).all():
        asyncio.run(handler(job, db))
        job.status = "completed"
        db.commit()


def _process(student, filename, data, content_type, findings, ocr=None,
             classification="transcript", holder=HOLDER):
    """Upload -> parse (fake OCR) -> extract (fake model) -> reconcile."""
    from app.memory.handlers import reconcile_memory

    file_id, storage_key = _upload(student, filename, data, content_type)
    ocr = ocr or _FakeOcr()
    store = _StubStore({storage_key: data})

    with student.factory() as db, \
            patch("app.documents.handlers.get_file_store", return_value=store), \
            patch("app.documents.ocr.get_ocr_provider", return_value=ocr), \
            patch("app.inference.gateway.complete", _model(findings, classification, holder)), \
            patch("app.documents.extractor._model_config", return_value=("test", "test", None)):
        _run_jobs(student, db, "document.parse", parse_document_job)
        _run_jobs(student, db, "document.extract", extract_document_job)
        _run_jobs(student, db, "memory.reconcile", reconcile_memory)
    return file_id, ocr


def _replay(student, findings, holder=HOLDER):
    """Run whatever extract and reconcile jobs are queued now (a card answer queues them)."""
    from app.memory.handlers import reconcile_memory

    with student.factory() as db, \
            patch("app.inference.gateway.complete", _model(findings, holder=holder)), \
            patch("app.documents.extractor._model_config", return_value=("test", "test", None)):
        _run_jobs(student, db, "document.extract", extract_document_job)
        _run_jobs(student, db, "memory.reconcile", reconcile_memory)


def _state_name(student, name, key="identity.full_name", reconcile=True):
    """The student said their name in chat; it is now the Vault's active name
    (or, with reconcile=False, a pending proposal not yet decided)."""
    with student.factory() as db:
        candidate = MemoryCandidateService(db).propose(
            workspace_id=student.workspace_id, candidate_type="vault_fact",
            key=key, proposed_value=name, confidence=0.95,
            source_type="conversation", input_channel="conversation",
            evidence={"quote": f"My name is {name}"})
        if reconcile:
            MemoryReconciler(db).reconcile(candidate)
        db.commit()


RESULT_FINDINGS = [
    _finding("vault_fact", "identity.full_name", "Ali Khan", "Name: Ali Khan"),
    _finding("student_record", "education",
             {"qualification_name": "HSSC Pre-Engineering",
              "result": {"marks_obtained": 920, "marks_total": 1100}},
             "HSSC Pre-Engineering"),
    _finding("student_record", "course",
             {"name": "Physics", "grade": "A", "score": {"marks_obtained": 85, "marks_total": 100}},
             "Physics | 85 / 100 | A"),
    _finding("student_record", "course",
             {"name": "Chemistry", "grade": "B", "score": {"marks_obtained": 78, "marks_total": 100}},
             "Chemistry | 78 / 100 | B"),
]


def test_jpeg_result_card_is_accepted_and_ocr_read():
    assert detect_document_type(JPEG, "result.jpg", "image/jpeg") == ("image", "image/jpeg")
    # The extension is a hint: a JPEG named .png is still a photo.
    assert detect_document_type(JPEG, "result.png", "") == ("image", "image/jpeg")
    parsed = parse_document(JPEG, "image")
    assert [s.text for s in parsed.segments] == [""]

    with VaultSession() as student:
        file_id, ocr = _process(student, "result.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)

        # OCR received the photo itself, not a re-render.
        assert ocr.sent == [(1, JPEG)]
        with student.factory() as db:
            artifact = DocumentArtifactService(db).get(student.workspace_id, file_id)
            assert artifact.status == "ready"
            assert artifact.document_type == "image"
            assert artifact.detected_content_type == "image/jpeg"
            assert artifact.ocr_used is True
            assert artifact.content["segments"][0]["ocr"] is True
            candidates = db.scalars(select(MemoryCandidate).where(
                MemoryCandidate.workspace_id == student.workspace_id,
                MemoryCandidate.source_type == "document")).all()
            assert "document" in {c.key for c in candidates}
            assert candidates and all(c.evidence.get("ocr") is True for c in candidates)
            # OCR-read values are never "shown" until the student confirms them.
            from app.models import EducationRecord
            from app.memory.student_snapshot import StudentSnapshotService
            courses = db.scalars(select(CourseRecord).where(
                CourseRecord.workspace_id == student.workspace_id)).all()
            education = db.scalars(select(EducationRecord).where(
                EducationRecord.workspace_id == student.workspace_id)).all()
            assert len(courses) == 2 and len(education) == 1
            assert {r.verification_status for r in [*courses, *education]} == {"extracted"}
            snapshot = StudentSnapshotService(db).build(student.workspace_id)
            name = snapshot.facts["identity.full_name"]
            assert name["evidence_level"] == "inferred"
            assert all(row["evidence_level"] != "shown"
                       for kind in ("education", "course") for row in snapshot.records[kind])


def _vision_url(data):
    sent = {}

    class _Completions:
        async def create(self, **kwargs):
            sent.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="x"))])

    class _Client:
        chat = SimpleNamespace(completions=_Completions())

        async def close(self):
            pass

    with patch("app.inference.gateway.get_client", return_value=_Client()):
        asyncio.run(VisionModelOcr(api_key="test", model="test").transcribe([(1, data)]))
    return sent["messages"][1]["content"][0]["image_url"]["url"]


def test_png_mime_is_png():
    assert _vision_url(PNG).startswith("data:image/png;base64,")
    assert _vision_url(JPEG).startswith("data:image/jpeg;base64,")


def test_photo_upload_is_registered_by_its_bytes():
    from app.routers.files import _register_student_document

    with VaultSession() as student, student.factory() as db:
        record = FileRecord(id=str(uuid.uuid4()), workspace_id=student.workspace_id,
                            filename="card.jpeg", content_type="application/octet-stream",
                            size=len(PNG), storage_key="test/card.jpeg",
                            uploaded_by=f"human:{student.user_id}")
        db.add(record)
        db.flush()
        # The browser said octet-stream and the name says JPEG; the bytes say PNG.
        status = _register_student_document(db, student.workspace_id, record.id, PNG,
                                            "card.jpeg", "application/octet-stream")
        assert status["status"] == "queued" and status["document_type"] == "image"
        artifact = DocumentArtifactService(db).get(student.workspace_id, record.id)
        assert artifact.detected_content_type == "image/png"


def test_transcript_subject_marks_become_courses():
    with VaultSession() as student:
        _process(student, "result.png", PNG, "image/png", RESULT_FINDINGS)
        with student.factory() as db:
            courses = {c.name: c for c in db.scalars(select(CourseRecord).where(
                CourseRecord.workspace_id == student.workspace_id)).all()}
            assert set(courses) == {"Physics", "Chemistry"}
            # Raw marks and their scale, as printed; nothing converted.
            assert courses["Physics"].score == {"marks_obtained": 85, "marks_total": 100}
            assert courses["Physics"].grade == "A"
            assert courses["Chemistry"].score == {"marks_obtained": 78, "marks_total": 100}
            from app.models import EducationRecord
            education = db.scalars(select(EducationRecord).where(
                EducationRecord.workspace_id == student.workspace_id)).one()
            assert {c.education_id for c in courses.values()} == {education.id}
            assert education.result == {"marks_obtained": 920, "marks_total": 1100}


def test_document_drop_is_logged():
    findings = [
        _finding("vault_item", "hobby", {"name": "Cricket"}, "Physics | 85 / 100 | A"),
        _finding("student_record", "course", {"name": "Biology", "grade": "A"}, "Biology 90 / 100"),
        _finding("vault_fact", "finance.budget", {"amount": 80000, "currency": "PKR"},
                 "Father's monthly income: 80000", locator="p1"),
    ]
    text = RESULT_CARD + "\nFather's monthly income: 80000"
    with VaultSession() as student:
        file_id, _ = _process(student, "card.jpg", JPEG, "image/jpeg", findings, ocr=_FakeOcr(text))
        with student.factory() as db:
            drops = db.scalars(select(VaultDrop).where(
                VaultDrop.workspace_id == student.workspace_id)).all()
    assert {d.source for d in drops} == {"document"}
    assert {d.stage for d in drops} == {"extract"}
    assert all(d.source_ref == file_id for d in drops)
    reasons = [d.reason for d in drops]
    assert any("hobby" in r for r in reasons)
    assert any("quote" in r for r in reasons)
    income = [d for d in drops if d.reason == "household_income"]
    assert len(income) == 1
    assert "80000" not in json.dumps(income[0].payload)


def test_someone_elses_document_is_not_applied():
    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        file_id, _ = _process(student, "result.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            assert db.scalars(select(CourseRecord).where(
                CourseRecord.workspace_id == student.workspace_id)).all() == []
            doc_candidates = db.scalars(select(MemoryCandidate).where(
                MemoryCandidate.workspace_id == student.workspace_id,
                MemoryCandidate.source_type == "document")).all()
            assert doc_candidates == []
            issues = db.scalars(select(ProfileIssue).where(
                ProfileIssue.workspace_id == student.workspace_id,
                ProfileIssue.issue_type == "document_owner")).all()
            assert len(issues) == 1
            assert issues[0].affected_id == file_id
            assert issues[0].evidence["file_id"] == file_id
            assert issues[0].status == "open"


def test_subset_name_document_is_applied():
    with VaultSession() as student:
        _state_name(student, "Muhammad Ali Khan")
        _process(student, "result.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            assert len(db.scalars(select(CourseRecord).where(
                CourseRecord.workspace_id == student.workspace_id)).all()) == 2
            assert db.scalars(select(ProfileIssue).where(
                ProfileIssue.workspace_id == student.workspace_id,
                ProfileIssue.issue_type == "document_owner")).all() == []


def test_document_prompt_lists_only_items_a_document_may_write():
    from app.documents.extractor import SYSTEM_PROMPT, document_item_types
    from app.memory.catalog import vault_catalog

    allowed = {spec.key for spec in document_item_types()}
    assert allowed == {spec.key for spec in vault_catalog().types(storage="item")
                       if "document" in spec.inputs}
    assert allowed and "<vault_items/>" not in SYSTEM_PROMPT
    for spec in vault_catalog().types(storage="item"):
        assert (f"- {spec.key}:" in SYSTEM_PROMPT) == (spec.key in allowed)
    assert "Never convert between scales" in SYSTEM_PROMPT


# -- fix round 1 ---------------------------------------------------------------

import pytest  # noqa: E402


def _rows(db, model, workspace_id, **filters):
    query = select(model).where(model.workspace_id == workspace_id)
    for name, value in filters.items():
        query = query.where(getattr(model, name) == value)
    return db.scalars(query).all()


def _state_education(student, marks):
    with student.factory() as db:
        candidate = MemoryCandidateService(db).propose(
            workspace_id=student.workspace_id, candidate_type="student_record", key="education",
            proposed_value={"qualification_name": "HSSC Pre-Engineering",
                            "result": {"marks_obtained": marks, "marks_total": 1100}},
            confidence=0.95, source_type="conversation", input_channel="conversation",
            evidence={"quote": f"I did HSSC Pre-Engineering and got {marks} out of 1100"})
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()


@pytest.mark.parametrize("action", ["accept_proposed", "keep_current"])
def test_courses_wait_for_the_education_card_and_are_saved_when_it_resolves(action):
    from app.memory.profile_issues import ProfileIssueService
    from app.models import EducationRecord

    with VaultSession() as student:
        _state_education(student, 900)
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            issue = _rows(db, ProfileIssue, student.workspace_id, issue_type="conflicting_record")
            assert len(issue) == 1
            waiting = issue[0].evidence["pending_course_candidate_ids"]
            assert len(waiting) == 2
            assert {c.status for c in _rows(db, MemoryCandidate, student.workspace_id, key="course")} == {"pending"}
            assert _rows(db, CourseRecord, student.workspace_id) == []

            ProfileIssueService(db).resolve(student.workspace_id, issue[0].id, action)
            db.commit()

            education = _rows(db, EducationRecord, student.workspace_id, status="active")
            assert len(education) == 1
            expected = 920 if action == "accept_proposed" else 900
            assert education[0].result["marks_obtained"] == expected
            courses = _rows(db, CourseRecord, student.workspace_id)
            assert {c.name for c in courses} == {"Physics", "Chemistry"}
            assert {c.education_id for c in courses} == {education[0].id}


def test_courses_link_to_an_education_the_document_corroborates():
    from app.models import EducationRecord

    with VaultSession() as student:
        _state_education(student, 920)
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            education = _rows(db, EducationRecord, student.workspace_id)
            courses = _rows(db, CourseRecord, student.workspace_id)
            assert len(education) == 1 and len(courses) == 2
            assert {c.education_id for c in courses} == {education[0].id}


INCOME_TEXT = RESULT_CARD + "\nFather's monthly income: 80000"


@pytest.mark.parametrize("finding", [
    _finding("vault_fact", "finance.budget", {"amount": 80000, "currency": "PKR"},
             "Father's monthly income: 80000", locator="p9"),
    _finding("vault_fact", "finance.budget", {"amount": 80000, "currency": "PKR"},
             "Father's monthly income: 80000 rupees exactly"),
    {**_finding("vault_fact", "finance.budget", {"amount": 80000, "currency": "PKR"},
                "Father's monthly income: 80000"), "confidence": "high"},
    _finding("vault_fact", "household_income", 80000, "Father's monthly income: 80000"),
], ids=["bad_locator", "invented_quote", "bad_confidence", "unknown_key"])
def test_document_income_is_dropped_before_any_other_check(finding):
    with VaultSession() as student:
        _process(student, "c.jpg", JPEG, "image/jpeg", [finding], ocr=_FakeOcr(INCOME_TEXT))
        with student.factory() as db:
            drops = _rows(db, VaultDrop, student.workspace_id)
    assert [d.reason for d in drops] == ["household_income"]
    assert "80000" not in json.dumps(drops[0].payload)


@pytest.mark.parametrize("raw", [
    {"candidate_type": "vault_fact", "key": "finance.budget", "proposed_value": {"amount": 80000},
     "quote": "Abbu ki tankhwah 80000 hai aur", "confidence": 0.9},
    {"candidate_type": "vault_fact", "key": "household_income", "proposed_value": 80000,
     "quote": "Abbu ki tankhwah 80000 hai", "confidence": "high"},
], ids=["invented_quote", "unknown_key_bad_confidence"])
def test_chat_income_is_dropped_before_any_other_check(raw):
    from app.memory.extractor import _validate

    turn = SimpleNamespace(user_text="Abbu ki tankhwah 80000 hai", user_event_id="e1", records={})
    drops = []
    assert _validate(raw, turn, {"finance.budget"}, drops) is None
    assert [d["reason"] for d in drops] == ["household_income"]
    assert "80000" not in json.dumps(drops[0]["payload"])


def _owner_issues(db, workspace_id):
    return _rows(db, ProfileIssue, workspace_id, issue_type="document_owner")


def test_romanized_name_variant_proceeds():
    with VaultSession() as student:
        _state_name(student, "Mohammad Ali Khan")
        findings = [_finding("vault_fact", "identity.full_name", "Muhammad Ali Khan", "Name: Ali Khan"),
                    *RESULT_FINDINGS[1:]]
        _process(student, "r.jpg", JPEG, "image/jpeg", findings,
                 holder={"value": "Muhammad Ali Khan", "quote": "Name: Ali Khan", "locator": "p1"})
        with student.factory() as db:
            assert _owner_issues(db, student.workspace_id) == []
            assert len(_rows(db, CourseRecord, student.workspace_id)) == 2


@pytest.mark.parametrize("vault, document, mismatch", [
    ({"full": ["Ali Raza Khan"]}, {"full": ["Khan"]}, True),
    ({"preferred": ["Ali"]}, {"full": ["Ali Hassan"]}, False),
    ({"preferred": ["Ali"]}, {"full": ["Hassan Ali"]}, True),
    ({"full": ["Muhammad Ali Khan"]}, {"full": ["Ali Khan"]}, False),
    ({"full": ["Syed Hussain Ahmed"]}, {"full": ["Sayyid Husain Ahmad"]}, False),
    ({"full": ["Fatima Zahra"]}, {"full": ["Fatimah Zahra"]}, False),
    ({"full": ["Sara Ahmed"]}, {"full": ["Ali Khan"]}, True),
    # Both sides have a full name: a matching preferred name does not rescue it.
    ({"full": ["Sara Ahmed"], "preferred": ["Ali"]}, {"full": ["Ali Khan"]}, True),
    ({}, {"full": ["Ali Khan"]}, False),
    ({"full": ["Ali Khan"]}, {}, False),
])
def test_owner_name_rules(vault, document, mismatch):
    from app.documents.owner import names_disagree

    assert names_disagree(document, vault) is mismatch


def test_single_family_name_on_a_document_is_a_mismatch():
    with VaultSession() as student:
        _state_name(student, "Ali Raza Khan")
        findings = [_finding("vault_fact", "identity.full_name", "Khan", "Ali Khan"), *RESULT_FINDINGS[1:]]
        _process(student, "r.jpg", JPEG, "image/jpeg", findings, holder=None)
        with student.factory() as db:
            assert len(_owner_issues(db, student.workspace_id)) == 1


def test_pending_name_proposal_counts_for_the_owner_check():
    with VaultSession() as student:
        _state_name(student, "Sara Ahmed", reconcile=False)
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            assert len(_owner_issues(db, student.workspace_id)) == 1


def test_owner_mismatch_logs_one_drop_without_values():
    findings = [*RESULT_FINDINGS, _finding("vault_item", "hobby", {"name": "x"}, "Name: Ali Khan")]
    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        file_id, _ = _process(student, "r.jpg", JPEG, "image/jpeg", findings)
        with student.factory() as db:
            drops = _rows(db, VaultDrop, student.workspace_id)
            issue = _owner_issues(db, student.workspace_id)[0]
    assert [(d.reason, d.payload, d.source_ref) for d in drops] == [
        ("document_owner_mismatch", {"file_id": file_id}, file_id)]
    assert issue.evidence["file_id"] == file_id
    assert "Ali Khan" in issue.evidence["document_names"]


def test_owner_card_its_mine_applies_the_document_once():
    from app.memory.profile_issues import ProfileIssueService

    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            issue = _owner_issues(db, student.workspace_id)[0]
            result = ProfileIssueService(db).resolve(student.workspace_id, issue.id, "accept_proposed")
            assert result["resolved"] is True
            db.commit()
        _replay(student, RESULT_FINDINGS)
        with student.factory() as db:
            assert len(_rows(db, CourseRecord, student.workspace_id)) == 2
            issues = _owner_issues(db, student.workspace_id)
            assert len(issues) == 1 and issues[0].status == "resolved"


def test_owner_card_keep_current_applies_nothing():
    from app.memory.profile_issues import ProfileIssueService

    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            issue = _owner_issues(db, student.workspace_id)[0]
            assert ProfileIssueService(db).resolve(
                student.workspace_id, issue.id, "keep_current")["resolved"] is True
            db.commit()
        _replay(student, RESULT_FINDINGS)
        with student.factory() as db:
            assert _rows(db, CourseRecord, student.workspace_id) == []
            assert _rows(db, MemoryCandidate, student.workspace_id, source_type="document") == []
            assert _owner_issues(db, student.workspace_id)[0].status == "resolved"


def test_document_without_a_holder_name_must_be_confirmed():
    from tests.documents.fixtures import make_pdf
    from app.models import EducationRecord

    pages = ["BOARD OF INTERMEDIATE EDUCATION LAHORE\nHSSC Pre-Engineering\nTotal 920 / 1100"]
    findings = [_finding("student_record", "education",
                         {"qualification_name": "HSSC Pre-Engineering"}, "HSSC Pre-Engineering")]
    with VaultSession() as student:
        _process(student, "r.pdf", make_pdf(pages), "application/pdf", findings, holder=None)
        with student.factory() as db:
            candidates = _rows(db, MemoryCandidate, student.workspace_id, key="education")
            assert candidates[0].evidence.get("owner_unverified") is True
            assert "ocr" not in candidates[0].evidence
            education = _rows(db, EducationRecord, student.workspace_id)
            assert [e.verification_status for e in education] == ["extracted"]


GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64


@pytest.mark.parametrize("filename, data, content_type", [
    ("photo.png", GIF, "image/png"), ("photo.jpg", WEBP, "image/jpeg")])
def test_other_images_are_stored_as_plain_files(filename, data, content_type):
    from app.documents.types import upload_rejection
    from app.routers.files import _register_student_document

    assert upload_rejection(data, filename, content_type) is None
    with VaultSession() as student, student.factory() as db:
        record = FileRecord(id=str(uuid.uuid4()), workspace_id=student.workspace_id,
                            filename=filename, content_type=content_type, size=len(data),
                            storage_key=f"test/{filename}", uploaded_by=f"human:{student.user_id}")
        db.add(record)
        db.flush()
        assert _register_student_document(db, student.workspace_id, record.id, data,
                                          filename, content_type) is None
        assert DocumentArtifactService(db).get(student.workspace_id, record.id) is None


def test_a_fake_pdf_is_still_rejected_at_upload():
    from app.documents.types import upload_rejection

    assert upload_rejection(GIF, "transcript.pdf", "application/pdf").code == "unsupported_type"


# -- fix round 1, follow-up: an OCR fact is PAI's guess -------------------------

def _active_name(db, workspace_id):
    from app.memory.vault import VaultService

    fact = VaultService(db).get_fact(workspace_id, "identity.full_name")
    return fact.value.get("value") if isinstance(fact.value, dict) else fact.value


@pytest.mark.parametrize("evidence", [{"ocr": True}, {"owner_unverified": True}])
def test_unconfirmed_document_reading_is_pais_guess(evidence):
    from app.memory.evidence import evidence_level

    row = {"source_type": "document", "verification_status": "document_supported",
           "evidence": {"authority": "institution_issued", "file_id": "f1", **evidence}}
    assert evidence_level(row, "Ali Khan") == "inferred"


def test_ocr_fact_cannot_replace_a_stated_fact():
    with VaultSession() as student:
        _state_name(student, "Ali Khan Durrani")
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            assert _active_name(db, student.workspace_id) == "Ali Khan Durrani"
            assert _rows(db, ProfileIssue, student.workspace_id, issue_type="conflicting_fact") == []
            ocr_name = [c for c in _rows(db, MemoryCandidate, student.workspace_id, key="identity.full_name")
                        if c.source_type == "document"]
            assert [c.status for c in ocr_name] == ["rejected"]


def test_student_statement_replaces_an_ocr_fact():
    from app.memory.student_snapshot import StudentSnapshotService

    with VaultSession() as student:
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            assert _active_name(db, student.workspace_id) == "Ali Khan"
            facts = StudentSnapshotService(db).build(student.workspace_id).facts
            assert facts["identity.full_name"]["evidence_level"] == "inferred"
        _state_name(student, "Muhammad Ali Khan")
        with student.factory() as db:
            assert _active_name(db, student.workspace_id) == "Muhammad Ali Khan"
            assert _rows(db, ProfileIssue, student.workspace_id, issue_type="conflicting_fact") == []
            facts = StudentSnapshotService(db).build(student.workspace_id).facts
            assert facts["identity.full_name"]["evidence_level"] == "stated"


# -- fix round 2 ---------------------------------------------------------------

def _chat_extract(proposals):
    from app.memory import extractor as ex

    turn = SimpleNamespace(user_text="Abbu ki tankhwah 80000 hai", user_event_id="e1", records={},
                           is_empty=lambda: False)

    async def fake(**kwargs):
        return json.dumps({"candidates": proposals})

    with patch.object(ex, "_model_config", return_value=("k", "m", None)), \
            patch.object(ex, "chat_completion", fake), \
            patch.object(ex, "build_user_prompt", lambda *a, **k: "p"), \
            patch.object(ex, "workspace_language_block", lambda *a, **k: ""):
        return asyncio.run(ex.extract_candidates(turn, {"finance.budget"}))


def test_chat_income_is_dropped_before_the_limit_and_over_limit_drops_hold_no_values():
    from app.memory import extractor as ex

    filler = [{"candidate_type": "vault_fact", "key": "finance.budget",
               "proposed_value": {"amount": 80000 + i}, "quote": "hai", "confidence": 0.9}
              for i in range(ex.MAX_CANDIDATES)]
    income = {"candidate_type": "vault_fact", "key": "finance.budget",
              "proposed_value": "father's income 80000 a month", "quote": "Abbu ki tankhwah 80000 hai",
              "confidence": 0.9}
    out = _chat_extract([income, *filler, dict(filler[0])])
    reasons = [d["reason"] for d in out.drops]
    assert reasons.count("household_income") == 1
    # The income proposal did not use up a slot: all the filler was validated, and
    # only the one past the limit was cut.
    assert reasons.count("over_candidate_limit") == 1
    over = next(d for d in out.drops if d["reason"] == "over_candidate_limit")
    assert set(over["payload"]) == {"candidate_type", "key"}
    assert not any("80000" in json.dumps(d) for d in out.drops if d["reason"] != "over_candidate_limit"
                   and d["reason"] == "household_income")


def test_document_income_is_dropped_before_the_limit():
    from app.documents import extractor as dx

    income = _finding("vault_fact", "finance.budget", {"amount": 80000}, "Father's monthly income: 80000")
    filler = [_finding("vault_item", "hobby", {"name": f"x{i}"}, "Name: Ali Khan") for i in range(dx.MAX_CANDIDATES)]
    with VaultSession() as student:
        _process(student, "c.jpg", JPEG, "image/jpeg", [income, *filler], ocr=_FakeOcr(INCOME_TEXT))
        with student.factory() as db:
            reasons = [d.reason for d in _rows(db, VaultDrop, student.workspace_id)]
    assert reasons.count("household_income") == 1
    assert "over_candidate_limit" not in reasons


@pytest.mark.parametrize("raw, dropped", [
    ({"candidate_type": "student_record", "key": "financial_sponsor",
      "proposed_value": {"sponsor_type": "parent", "details": {"amount": 80000}},
      "quote": "Abbu ki tankhwah 80000 hai", "confidence": 0.9}, True),
    ({"candidate_type": "student_record", "key": "financial_sponsor",
      "proposed_value": {"sponsor_type": "parent", "details": {"amount": 300000, "currency": "PKR"}},
      "quote": "Abbu fees ke liye 3 lakh denge", "confidence": 0.9}, False),
])
def test_finance_record_kinds_are_income_guarded(raw, dropped):
    from app.memory.extractor import _validate

    turn = SimpleNamespace(user_text=raw["quote"], user_event_id="e1", records={})
    drops = []
    candidate = _validate(raw, turn, {"finance.budget"}, drops)
    if dropped:
        assert candidate is None and [d["reason"] for d in drops] == ["household_income"]
        assert "80000" not in json.dumps(drops[0]["payload"])
    else:
        assert candidate is not None and "household_income" not in [d["reason"] for d in drops]


def test_owner_card_provide_new_with_another_name_applies_nothing():
    from app.memory.profile_issues import ProfileIssueService

    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            issue = _owner_issues(db, student.workspace_id)[0]
            ProfileIssueService(db).resolve(student.workspace_id, issue.id, "provide_new",
                                            value="It's my brother Ali's")
            db.commit()
            db.refresh(issue)
            assert issue.status == "resolved" and issue.resolution["action"] == "keep_current"
            assert issue.resolution["note"]
        _replay(student, RESULT_FINDINGS)
        with student.factory() as db:
            assert _rows(db, CourseRecord, student.workspace_id) == []
            assert _rows(db, MemoryCandidate, student.workspace_id, source_type="document") == []


def test_owner_card_provide_new_with_the_holder_name_applies_the_document():
    from app.memory.profile_issues import ProfileIssueService

    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            issue = _owner_issues(db, student.workspace_id)[0]
            ProfileIssueService(db).resolve(student.workspace_id, issue.id, "provide_new",
                                            value="Muhammad Ali Khan")
            db.commit()
        _replay(student, RESULT_FINDINGS)
        with student.factory() as db:
            assert len(_rows(db, CourseRecord, student.workspace_id)) == 2


def test_owner_confirmed_replay_runs_once():
    from app.memory.profile_issues import ProfileIssueService

    with VaultSession() as student:
        _state_name(student, "Sara Ahmed")
        file_id, _ = _process(student, "r.jpg", JPEG, "image/jpeg", RESULT_FINDINGS)
        with student.factory() as db:
            issue = _owner_issues(db, student.workspace_id)[0]
            ProfileIssueService(db).resolve(student.workspace_id, issue.id, "accept_proposed")
            db.commit()
            payload = db.scalars(select(BackgroundJob).where(
                BackgroundJob.workspace_id == student.workspace_id,
                BackgroundJob.job_type == "document.extract",
                BackgroundJob.status == "pending")).one().payload
        _replay(student, RESULT_FINDINGS)
        with student.factory() as db:
            first = len(_rows(db, MemoryCandidate, student.workspace_id, source_type="document"))
            assert first > 0
            assert _owner_issues(db, student.workspace_id)[0].evidence.get("replayed_at")
            job = SimpleNamespace(id="retry", workspace_id=student.workspace_id, payload=payload,
                                  job_type="document.extract")
            with patch("app.inference.gateway.complete", _model(RESULT_FINDINGS)), \
                    patch("app.documents.extractor._model_config", return_value=("test", "test", None)):
                result = asyncio.run(extract_document_job(job, db))
            db.commit()
            assert result["extracted"] is False
            assert len(_rows(db, MemoryCandidate, student.workspace_id, source_type="document")) == first


def _fact(student, value, source_type, evidence):
    with student.factory() as db:
        candidate = MemoryCandidateService(db).propose(
            workspace_id=student.workspace_id, candidate_type="vault_fact", key="identity.full_name",
            proposed_value=value, confidence=0.95, source_type=source_type,
            input_channel="conversation" if source_type == "conversation" else "document",
            evidence=evidence)
        MemoryReconciler(db).reconcile(candidate)
        db.commit()


@pytest.mark.parametrize("extra, clears", [
    ({"ocr": True}, False), ({"owner_unverified": True}, False), ({}, True)])
def test_only_a_trusted_document_clears_a_chat_guess(extra, clears):
    from app.memory.vault import VaultService

    with VaultSession() as student:
        _fact(student, "Ali Khan", "conversation", {"quote": "Ali Khan", "inferred": True})
        _fact(student, "Ali Khan", "document",
              {"quote": "Name: Ali Khan", "authority": "institution_issued", "file_id": "f1", **extra})
        with student.factory() as db:
            fact = VaultService(db).get_fact(student.workspace_id, "identity.full_name")
            assert bool(fact.evidence.get("inferred")) is (not clears)
