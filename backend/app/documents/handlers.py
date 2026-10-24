# -*- coding: utf-8 -*-
"""Durable job handlers for the document pipeline.

    document.parse    bytes  -> normalized segments (+ OCR fallback)
    document.extract  segments -> classification + MemoryCandidates
    document.index    segments -> derived retrieval chunks
    document.unindex  purge    -> remove chunks

Each stage is its own job so they retry independently. The ordering rule that
matters: **indexing failure must never roll back canonical writes.** Indexing
is therefore enqueued after extraction commits, not called inline.

Registered on import, like `app/memory/handlers.py`; the worker imports both.
"""

from __future__ import annotations

import logging

from app.files.storage import get_file_store
from app.memory.errors import MemoryDataError
from .content import ParsedDocument, Segment, segments_from_content
from .parsers import (
    DocumentParseError, MAX_CONTENT_CHARS, parse_document, pages_needing_ocr,
    render_pdf_page_png, truncate_segments,
)
from .service import (
    JOB_DOCUMENT_EXTRACT, JOB_DOCUMENT_INDEX, JOB_DOCUMENT_NOTIFY,
    JOB_DOCUMENT_PARSE, JOB_DOCUMENT_UNINDEX, PARSER_VERSION,
    DocumentArtifactService,
)

logger = logging.getLogger(__name__)


def _load_bytes(db, workspace_id: str, file_id: str) -> bytes | None:
    """Read the raw file from workspace storage."""
    from sqlalchemy import select

    from app.models import FileRecord

    record = db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    try:
        return get_file_store().read(record.storage_key)
    except Exception:  # noqa: BLE001 — a missing object is a real, safe outcome
        logger.warning("document bytes unreadable file=%s", file_id, exc_info=True)
        return None


async def _apply_ocr(data: bytes, parsed: ParsedDocument) -> ParsedDocument:
    """Fill in pages that deterministic extraction could not read.

    Returns the document unchanged when OCR is unavailable, marking it
    `partial` — a scanned upload should land and be reprocessable later, not
    fail outright.
    """
    from .ocr import MAX_OCR_PAGES, get_ocr_provider

    blank_pages = pages_needing_ocr(parsed)
    if not blank_pages:
        return parsed

    provider = get_ocr_provider()
    if provider is None:
        logger.info("document ocr unavailable, %d page(s) unread", len(blank_pages))
        parsed.partial = True
        return parsed

    targets = blank_pages[:MAX_OCR_PAGES]
    images: list[tuple[int, bytes]] = []
    for page_number in targets:
        if parsed.document_type == "image":
            # The photo itself: re-encoding it would only lose detail.
            images.append((page_number, data))
            continue
        try:
            images.append((page_number, render_pdf_page_png(data, page_number)))
        except Exception:  # noqa: BLE001 — one unrenderable page is not fatal
            logger.warning("document page render failed page=%d", page_number, exc_info=True)

    if not images:
        parsed.partial = True
        return parsed

    try:
        results = await provider.transcribe(images)
    except Exception:  # noqa: BLE001 — OCR outage must not lose the upload
        logger.warning("document ocr failed", exc_info=True)
        parsed.partial = True
        return parsed

    by_page = {page.page_number: page.text for page in results}
    filled = 0
    for index, segment in enumerate(parsed.segments, start=1):
        text = (by_page.get(index) or "").strip()
        if text and len(segment.text) < len(text):
            segment.text = text
            segment.ocr = True
            filled += 1

    parsed.ocr_used = filled > 0
    parsed.ocr_provider = provider.name if filled else None
    # Pages beyond the cap, or that OCR could not read, remain unread.
    parsed.partial = parsed.partial or len(blank_pages) > len(targets) or filled < len(targets)

    kept, truncated = truncate_segments(parsed.segments, MAX_CONTENT_CHARS)
    parsed.segments = kept
    parsed.truncated = parsed.truncated or truncated
    return parsed


async def parse_document_job(job, db) -> dict:
    """Parse one uploaded document into normalized, located segments."""
    workspace_id = job.workspace_id
    payload = job.payload or {}
    file_id = payload.get("file_id")
    if not workspace_id or not file_id:
        raise ValueError("document.parse requires workspace_id and file_id")

    service = DocumentArtifactService(db)
    artifact = service.get(workspace_id, file_id)
    if artifact is None:
        # The file (or its workspace) went away before the job ran. Nothing to
        # parse and nothing to retry.
        logger.info("document.parse: artifact missing workspace=%s file=%s",
                    workspace_id, file_id)
        return {"parsed": False, "reason": "artifact_missing"}

    if artifact.status == "unsupported":
        return {"parsed": False, "reason": "unsupported"}

    # Idempotency: a completed parse at the current parser version is not
    # redone by a retry or a duplicate enqueue.
    if artifact.status in ("ready", "partial") and artifact.parser_version == PARSER_VERSION:
        return {"parsed": False, "reason": "already_parsed"}

    data = _load_bytes(db, workspace_id, file_id)
    if data is None:
        service.mark_failed(
            artifact, "file_unavailable",
            "The uploaded file could not be read from storage.",
        )
        return {"parsed": False, "reason": "file_unavailable"}

    service.mark_processing(artifact)

    try:
        parsed = parse_document(data, artifact.document_type or "")
    except DocumentParseError as exc:
        # A statement about the document, not a transient fault: record it and
        # succeed, so the durable worker does not retry a permanently
        # unparseable file five times.
        logger.info("document.parse failed file=%s code=%s", file_id, exc.code)
        service.mark_failed(artifact, exc.code, exc.message)
        return {"parsed": False, "reason": exc.code}

    if parsed.document_type in ("pdf", "image"):
        parsed = await _apply_ocr(data, parsed)

    service.mark_parsed(
        artifact,
        content=parsed.to_content(),
        parser=parsed.parser,
        page_count=parsed.page_count,
        char_count=parsed.char_count,
        ocr_used=parsed.ocr_used,
        ocr_provider=parsed.ocr_provider,
        partial=parsed.partial,
    )

    logger.info(
        "document.parse: workspace=%s file=%s type=%s parser=%s pages=%d chars=%d "
        "ocr=%s partial=%s truncated=%s",
        workspace_id, file_id, parsed.document_type, parsed.parser,
        parsed.page_count, parsed.char_count, parsed.ocr_used, parsed.partial,
        parsed.truncated,
    )

    # Extraction is its own durable job: parsing succeeded and must not be
    # redone because an LLM call failed.
    from app.runtime.task_runtime import enqueue

    enqueue(db,
        job_type=JOB_DOCUMENT_EXTRACT,
        workspace_id=workspace_id,
        payload={"file_id": file_id},
        idempotency_key=(
            f"document.extract:{file_id}:{artifact.content_sha256}:{PARSER_VERSION}"
        ),
    )

    return {
        "parsed": True,
        "pages": parsed.page_count,
        "chars": parsed.char_count,
        "ocr_used": parsed.ocr_used,
        "partial": parsed.partial,
    }


_NAME_KEYS = ("identity.full_name", "identity.preferred_name")


def _is_education(finding) -> bool:
    return finding.candidate_type == "student_record" and finding.key == "education"


def _names(pairs) -> dict:
    """{"full": [...], "preferred": [...]} from (key, value) pairs."""
    out: dict = {"full": [], "preferred": []}
    for key, value in pairs:
        if isinstance(value, dict):
            value = value.get("value")
        if isinstance(value, str) and value.strip():
            out["full" if key == "identity.full_name" else "preferred"].append(value.strip())
    return out


def _owner_mismatch(db, workspace_id: str, understanding) -> dict | None:
    """The names on the document and the student's names, when no pair agrees.

    The student's side is the active Vault name plus any name proposal not
    yet decided (a name said a moment ago still counts). The document's side
    is its holder name and any name it proposes. See `owner.py` for the rules.
    """
    from sqlalchemy import select

    from app.memory.vault import VaultService
    from app.models import MemoryCandidate
    from .owner import names_disagree

    document = _names(
        [("identity.full_name", understanding.holder_name)]
        + [(f.key, f.proposed_value) for f in understanding.findings
           if f.candidate_type == "vault_fact" and f.key in _NAME_KEYS])
    vault_service = VaultService(db)
    pending = db.execute(select(MemoryCandidate).where(
        MemoryCandidate.workspace_id == workspace_id,
        MemoryCandidate.candidate_type == "vault_fact",
        MemoryCandidate.key.in_(_NAME_KEYS),
        MemoryCandidate.status == "pending",
        MemoryCandidate.source_type != "document",
    )).scalars().all()
    vault = _names(
        [(key, fact.value) for key in _NAME_KEYS
         if (fact := vault_service.get_fact(workspace_id, key)) is not None]
        + [(c.key, c.proposed_value) for c in pending])
    if not names_disagree(document, vault):
        return None
    return {"document_names": document["full"] + document["preferred"],
            "vault_names": vault["full"] + vault["preferred"]}


def _open_owner_issue(db, workspace_id: str, file_id: str, filename: str, names: dict) -> None:
    from app.models import ProfileIssue

    db.add(ProfileIssue(
        workspace_id=workspace_id, issue_type="document_owner", severity="blocking",
        affected_type="document", affected_id=file_id,
        summary=f"The name on {filename or 'this document'} does not match the student's name",
        clarification_question=(
            f"The name on {filename or 'this document'} is different from yours. "
            "Is this your document?"),
        evidence={"file_id": file_id, "filename": filename, **names},
    ))
    db.flush()
    logger.info("document.extract: owner mismatch, nothing applied file=%s", file_id)


async def extract_document_job(job, db) -> dict:
    """Understand a parsed document and propose candidates.

    This function may ONLY write `pai_memory_candidates`. It has no access to
    VaultService or StudentRecordService, so even a compromised extraction
    prompt cannot change canonical state — the reconciler decides, exactly as
    it does for conversation.
    """
    from app.memory.candidates import MemoryCandidateService
    from app.memory.field_definitions import VaultFieldDefinitionService
    from app.memory.student_snapshot import StudentSnapshotService
    from .classify import authority_for, is_journey_document
    from .extractor import EXTRACTOR_VERSION, DocumentExtractionError, understand_document

    workspace_id = job.workspace_id
    file_id = (job.payload or {}).get("file_id")
    if not workspace_id or not file_id:
        raise ValueError("document.extract requires workspace_id and file_id")
    # The student answered "it's mine" on the owner card: this one replay
    # skips the owner check and re-reads a document already understood.
    owner_confirmed = bool((job.payload or {}).get("owner_confirmed"))

    service = DocumentArtifactService(db)
    artifact = service.get(workspace_id, file_id)
    if artifact is None:
        return {"extracted": False, "reason": "artifact_missing"}
    if artifact.status not in ("ready", "partial"):
        return {"extracted": False, "reason": f"not_readable:{artifact.status}"}
    if (artifact.extractor_version == EXTRACTOR_VERSION and artifact.classification
            and not owner_confirmed):
        # Already understood at this version — a retry must not propose the
        # same candidates twice.
        return {"extracted": False, "reason": "already_extracted"}

    segments = segments_from_content(artifact.content)
    if not any(segment.text.strip() for segment in segments):
        # A photo OCR could not read has one empty page: nothing to send a model.
        return {"extracted": False, "reason": "no_content"}

    # Existing state comes from the shared snapshot — never a second view of
    # "what we know", which would drift from the canonical one.
    snapshot = StudentSnapshotService(db).build(workspace_id)
    definitions = VaultFieldDefinitionService(db).list_definitions()
    allowed_keys = {d.key for d in definitions}
    field_specs = [
        {"key": d.key, "data_type": d.data_type, "description": d.description}
        for d in definitions
    ]

    from sqlalchemy import select

    from app.models import FileRecord

    record = db.execute(
        select(FileRecord).where(FileRecord.id == file_id)
    ).scalar_one_or_none()
    filename = (record.filename if record else "").rsplit("/", 1)[-1]
    uploaded_by = record.uploaded_by if record else ""

    try:
        understanding = await understand_document(
            segments, filename=filename,
            document_type=artifact.document_type or "",
            allowed_vault_keys=allowed_keys, field_specs=field_specs,
            existing_records=snapshot.records,
        )
    except DocumentExtractionError:
        # Malformed output fails the job so the durable worker retries, rather
        # than writing half-trusted rows.
        logger.warning("document.extract: bad model output file=%s", file_id)
        raise

    authority = authority_for(understanding.classification, uploaded_by)
    service.record_classification(
        artifact,
        classification=understanding.classification,
        confidence=understanding.classification_confidence,
        authority=authority,
        extractor_version=EXTRACTOR_VERSION,
        summary={"findings": len(understanding.findings)},
    )

    from app.memory.candidates import record_drop

    candidates = MemoryCandidateService(db)
    proposed: list[str] = []

    # Another person's document is not applied, and the student is asked
    # (VAULT_SPEC §Conflicts). Decided over all of the document's names at
    # once, before anything from it is proposed.
    mismatch = None if owner_confirmed else _owner_mismatch(db, workspace_id, understanding)
    if mismatch is not None:
        _open_owner_issue(db, workspace_id, file_id, filename, mismatch)
        # One row for the whole document: its values are someone else's.
        record_drop(db, workspace_id, "document", "extract", "document_owner_mismatch",
                    {"file_id": file_id}, source_ref=file_id)
        findings = []
    else:
        for dropped in understanding.drops:
            record_drop(db, workspace_id, "document", "extract", dropped["reason"],
                        dropped["payload"], source_ref=file_id)
        # Qualifications first, so a course can name the record its
        # qualification became when the reconciler reaches it.
        findings = sorted(understanding.findings, key=lambda f: not _is_education(f))
    educations = [f for f in findings if _is_education(f)]
    education_candidate_id = None
    # A result card with no readable holder name cannot be tied to this
    # student, so like an OCR reading it waits for the student to confirm.
    owner_unverified = (not owner_confirmed and not understanding.holder_name
                        and any(f.candidate_type == "student_record" and f.key in ("education", "course")
                                for f in findings))
    trust = {
        **({"ocr": True} if artifact.ocr_used else {}),
        **({"owner_unverified": True} if owner_unverified else {}),
        **({"owner_confirmed": True} if owner_confirmed else {}),
    }

    # A StudentDocument record: "this file is a meaningful journey document".
    # The file_id is SERVER-owned — taken from the job, never from model
    # output — so a model cannot name a file it was not given.
    if mismatch is None and is_journey_document(understanding.classification) and record is not None:
        existing_documents = {
            row.get("file_id") for row in snapshot.records.get("document", [])
        }
        if file_id not in existing_documents:
            try:
                candidate = candidates.propose(
                    workspace_id=workspace_id,
                    candidate_type="student_record",
                    key="document",
                    proposed_value={
                        "file_id": file_id,
                        "document_type": understanding.classification,
                        **({"title": understanding.title} if understanding.title else {}),
                    },
                    confidence=max(0.5, understanding.classification_confidence),
                    source_type="document",
                    input_channel="document",
                    evidence={
                        "file_id": file_id, "filename": filename,
                        "authority": authority,
                        "extractor_version": EXTRACTOR_VERSION,
                        **({"ocr": True} if artifact.ocr_used else {}),
                    },
                )
            except MemoryDataError as exc:
                logger.info("document.extract: normalize rejected document record file=%s: %s", file_id, exc)
            else:
                proposed.append(candidate.id)

    for finding in findings:
        proposed_value = finding.proposed_value
        entities = dict(finding.entities or {})
        if finding.candidate_type == "student_record" and finding.key == "credential" and isinstance(proposed_value, dict):
            # The source file belongs to this job, not to the extractor's JSON.
            proposed_value = {**proposed_value, "raw_document_ref": file_id}
        if entities.pop("education_from_document", False):
            # A subject's marks belong to the one qualification this document
            # names; with none, or several, there is no honest link to make.
            existing_id = (educations[0].entities or {}).get("record_id") if len(educations) == 1 else None
            if existing_id:
                proposed_value = {**proposed_value, "education_id": existing_id}
            elif len(educations) == 1 and education_candidate_id:
                entities["education_candidate_id"] = education_candidate_id
            else:
                reason = ("course_without_education" if len(educations) != 1
                          else "course_education_not_proposed")
                logger.info("document.extract: dropped course file=%s: %s", file_id, reason)
                record_drop(db, workspace_id, "document", "extract", reason,
                            {"candidate_type": finding.candidate_type, "key": finding.key,
                             "proposed_value": proposed_value}, source_ref=file_id)
                continue
        try:
            candidate = candidates.propose(
                workspace_id=workspace_id,
                candidate_type=finding.candidate_type,
                operation="upsert",
                key=finding.key,
                proposed_value=proposed_value,
                content=finding.content,
                entities=entities or None,
                confidence=finding.confidence,
                # Server-assigned, from the channel this job read. The extractor
                # has no field for it and cannot reach `user_explicit`.
                source_type="document",
                input_channel="document",
                evidence={
                    **finding.evidence,
                    "file_id": file_id,
                    "filename": filename,
                    "document_type": understanding.classification,
                    "authority": authority,
                    "parser": artifact.parser,
                    "parser_version": artifact.parser_version,
                    "extractor_version": EXTRACTOR_VERSION,
                    **trust,
                },
            )
        except MemoryDataError as exc:
            logger.info("document.extract: normalize rejected %s file=%s: %s", finding.key, file_id, exc)
            continue
        proposed.append(candidate.id)
        if _is_education(finding):
            education_candidate_id = candidate.id

    logger.info(
        "document.extract: workspace=%s file=%s class=%s authority=%s "
        "findings=%d proposed=%d types=%s",
        workspace_id, file_id, understanding.classification, authority,
        len(understanding.findings), len(proposed),
        sorted({f.candidate_type for f in understanding.findings}) or None,
    )

    # Which candidates came from THIS document, so progress reporting can say
    # what it actually changed. Counts and ids only — never content.
    artifact.extraction_summary = {
        "findings": len(understanding.findings),
        "candidate_ids": proposed,
    }
    db.flush()

    from app.runtime.task_runtime import enqueue

    if proposed:
        # Reconciliation is the EXISTING durable job — documents converge on
        # the same path as conversation rather than getting their own.
        # `document_file_id` asks it to report back when it has decided, so
        # the completion message describes real outcomes, not proposals.
        from app.memory.handlers import JOB_RECONCILE

        enqueue(db,
            job_type=JOB_RECONCILE,
            workspace_id=workspace_id,
            payload={"candidate_ids": proposed, "document_file_id": file_id},
            idempotency_key=(f"reconcile:document:{file_id}:{EXTRACTOR_VERSION}"
                             + (":owner_confirmed" if owner_confirmed else "")),
        )
    else:
        # Nothing to reconcile: tell the student now rather than never.
        enqueue_document_notify(db, workspace_id, file_id)

    # Indexing is enqueued separately and AFTER extraction, so an index
    # failure can never roll back canonical writes.
    from app.config import config
    if config.PAI_SEMANTIC_RECALL_ENABLED:
        enqueue(db,
            job_type=JOB_DOCUMENT_INDEX,
            workspace_id=workspace_id,
            payload={"file_id": file_id},
            idempotency_key=f"document.index:{file_id}:{artifact.content_sha256}",
        )

    return {
        "extracted": True,
        "classification": understanding.classification,
        "authority": authority,
        "candidates_proposed": len(proposed),
    }


def enqueue_document_notify(db, workspace_id: str, file_id: str) -> None:
    """Queue the "I've finished reading your document" chat message."""
    from app.runtime.task_runtime import enqueue
    from .extractor import EXTRACTOR_VERSION

    enqueue(db,
        job_type=JOB_DOCUMENT_NOTIFY,
        workspace_id=workspace_id,
        payload={"file_id": file_id},
        # One message per document per extractor version: a retried
        # reconcile must not post twice.
        idempotency_key=f"document.notify:{file_id}:{EXTRACTOR_VERSION}",
        max_attempts=3,
    )


async def notify_document_job(job, db) -> dict:
    """Post a completion message into the chat the document was attached in.

    Without this, a student who navigated away came back to a thread that
    looked stalled, even though the document had long since been processed.
    The message is built from what the reconciler actually decided, so it
    cannot claim a save that did not happen.

    A document uploaded outside a chat (e.g. the file browser) has no thread
    to post into; its status is still visible to the Counselor each turn.
    """
    from sqlalchemy import select

    from app.models import FileRecord
    from app.pai_c.orchestrator import handle_document_update
    from app.services.pai import PAI_AGENT_NAME
    from .progress import completion_message, learned_summary

    workspace_id = job.workspace_id
    file_id = (job.payload or {}).get("file_id")
    if not workspace_id or not file_id:
        raise ValueError("document.notify requires workspace_id and file_id")

    artifact = DocumentArtifactService(db).get(workspace_id, file_id)
    record = db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id, FileRecord.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if artifact is None or record is None or record.status != "active":
        return {"posted": False, "reason": "document_gone"}
    if not record.channel_name:
        return {"posted": False, "reason": "no_chat"}

    summary = learned_summary(db, artifact)
    message = completion_message(record.filename, artifact.classification or "", summary)
    event_id = await handle_document_update(
        db, workspace_id, f"channel/{record.channel_name}", PAI_AGENT_NAME,
        message, depth=0, message_type="document_processed",
        metadata={"document_file_id": file_id},
    )
    logger.info(
        "document.notify: workspace=%s file=%s posted=%s learned=%d needs_review=%d",
        workspace_id, file_id, bool(event_id),
        sum((summary.get("learned") or {}).values()), summary.get("needs_review", 0),
    )
    return {"posted": bool(event_id)}


async def index_document_job(job, db) -> dict:
    """Index a parsed document's chunks for later retrieval (Phase F)."""
    from .retrieval import index_document_chunks

    workspace_id = job.workspace_id
    file_id = (job.payload or {}).get("file_id")
    if not workspace_id or not file_id:
        raise ValueError("document.index requires workspace_id and file_id")

    artifact = DocumentArtifactService(db).get(workspace_id, file_id)
    if artifact is None or not artifact.content:
        return {"indexed": 0, "reason": "no_content"}

    indexed = await index_document_chunks(
        workspace_id=workspace_id,
        file_id=file_id,
        document_type=artifact.classification or artifact.document_type or "",
        segments=segments_from_content(artifact.content),
    )
    logger.info(
        "document.index: workspace=%s file=%s chunks=%d", workspace_id, file_id, indexed,
    )
    return {"indexed": indexed}


async def unindex_document_job(job, db) -> dict:
    """Remove purged documents from the derived retrieval index."""
    from .retrieval import delete_document_chunks

    workspace_id = job.workspace_id
    file_ids = (job.payload or {}).get("file_ids") or []
    if not workspace_id:
        raise ValueError("document.unindex requires a workspace_id")
    if not file_ids:
        return {"deleted": 0}

    deleted = await delete_document_chunks(workspace_id, file_ids)
    logger.info(
        "document.unindex: workspace=%s files=%d deleted=%d",
        workspace_id, len(file_ids), deleted,
    )
    return {"deleted": deleted}


