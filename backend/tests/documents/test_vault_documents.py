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


def _process(student, filename, data, content_type, findings, ocr=None,
             classification="transcript"):
    """Upload -> parse (fake OCR) -> extract (fake model) -> reconcile."""
    file_id, storage_key = _upload(student, filename, data, content_type)
    ocr = ocr or _FakeOcr()
    store = _StubStore({storage_key: data})

    async def fake_model(**kwargs):
        return json.dumps({"classification": classification, "classification_confidence": 0.9,
                           "title": "Result card", "findings": findings})

    with student.factory() as db, \
            patch("app.documents.handlers.get_file_store", return_value=store), \
            patch("app.documents.ocr.get_ocr_provider", return_value=ocr), \
            patch("app.inference.gateway.complete", fake_model), \
            patch("app.documents.extractor._model_config", return_value=("test", "test", None)):
        asyncio.run(parse_document_job(_job(student, file_id, "document.parse"), db))
        db.commit()
        asyncio.run(extract_document_job(_job(student, file_id, "document.extract"), db))
        db.commit()
        from app.memory.handlers import reconcile_memory
        for job in db.scalars(select(BackgroundJob).where(
                BackgroundJob.workspace_id == student.workspace_id,
                BackgroundJob.job_type == "memory.reconcile",
                BackgroundJob.status == "pending")).all():
            asyncio.run(reconcile_memory(job, db))
            job.status = "completed"
            db.commit()
    return file_id, ocr


def _state_name(student, name):
    """The student said their name in chat; it is now the Vault's active name."""
    with student.factory() as db:
        candidate = MemoryCandidateService(db).propose(
            workspace_id=student.workspace_id, candidate_type="vault_fact",
            key="identity.full_name", proposed_value=name, confidence=0.95,
            source_type="conversation", input_channel="conversation",
            evidence={"quote": f"My name is {name}"})
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
                MemoryCandidate.key != "document")).all()
            assert candidates and all(c.evidence.get("ocr") is True for c in candidates)
            # OCR-read values are never "shown" until the student confirms them.
            courses = db.scalars(select(CourseRecord).where(
                CourseRecord.workspace_id == student.workspace_id)).all()
            assert courses and all(c.verification_status != "document_supported" for c in courses)


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
