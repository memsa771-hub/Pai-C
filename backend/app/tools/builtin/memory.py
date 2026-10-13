# -*- coding: utf-8 -*-
"""Registered memory read handlers and the profile-proposal write seam.

Tool declarations live in app/tools/builtin/__init__.py. Profile proposals
enter the existing candidate and queued reconciliation path.
"""

import logging

from app.database import new_session
from app.memory.candidates import MemoryCandidateService
from app.memory.context import MemoryContextService
from app.memory.vault import VaultService
from app.memory.field_definitions import usable_in_counseling

logger = logging.getLogger(__name__)


def _session():
    """Own session per tool call.

    Tool handlers are async and run inside a threadpool request; borrowing the
    request's Session would hold a pooled connection across an await.
    """
    return new_session()


# -- reads (Counselor + Operator) -----------------------------------------


async def get_context(context, args: dict) -> dict:
    """Assemble compact student context. The main read path."""
    db = _session()
    try:
        from app.memory.student_context import StudentContextBuilder
        student = StudentContextBuilder(db).build_context(
            context.workspace_id, query=args.get("query"), caller=context.agent_name,
            intent=args.get("intent"))
        return {"ok": True, "data": student.to_dict()}
    finally:
        db.close()


async def vault_get(context, args: dict) -> dict:
    """Read Vault facts — the whole snapshot, or one field with provenance."""
    db = _session()
    try:
        vault = VaultService(db)
        field_key = args.get("field_key")
        if field_key:
            definition = vault.fields.get(field_key)
            if definition is not None and not usable_in_counseling(definition):
                return {"ok": False, "error": {"code": "sensitive_field", "message": "This field is not available in conversational context"}}
            fact = vault.get_fact(context.workspace_id, field_key)
            if fact is None:
                return {"ok": True, "data": {"field_key": field_key, "value": None}}
            return {"ok": True, "data": {
                "field_key": field_key,
                "value": (fact.value or {}).get("value"),
                "confidence": fact.confidence,
                "source_type": fact.source_type,
                "claim_origin": fact.claim_origin,
                "capture_method": fact.capture_method,
                "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
            }}
        from app.memory.student_records import StudentRecordService
        from app.memory.readiness import ReadinessService
        from app.memory.student_context import StudentContextBuilder
        profile = StudentContextBuilder(db).build_context(
            context.workspace_id, query=args.get("query"), caller=context.agent_name,
            intent=args.get("intent"))
        from app.memory.student_schema import extraction_specs
        return {"ok": True, "data": {
            "fields": profile.vault,
            "records": profile.records,
            "record_schemas": extraction_specs(),
            "issues": [
                {"id": issue.id, "type": issue.issue_type, "summary": issue.summary}
                for issue in StudentRecordService(db).issues(context.workspace_id)
            ],
            "readiness": ReadinessService(db).evaluate(context.workspace_id, "discovery"),
        }}
    finally:
        db.close()


async def memory_search(context, args: dict) -> dict:
    """Search semantic memories."""
    from app.memory.semantic import MemoryService

    db = _session()
    try:
        service = MemoryService(db)
        found = service.search(
            context.workspace_id,
            args.get("query", ""),
            limit=min(int(args.get("limit", 10)), 50),
            memory_type=args.get("memory_type"),
        )
        return {"ok": True, "data": {"memories": [MemoryService.to_dict(m) for m in found]}}
    finally:
        db.close()


async def episodes_recent(context, args: dict) -> dict:
    """Recent episodes — what has happened lately."""
    from app.memory.episodic import EpisodicMemoryService

    db = _session()
    try:
        service = EpisodicMemoryService(db)
        found = service.recent(
            context.workspace_id,
            limit=min(int(args.get("limit", 10)), 50),
            event_type=args.get("event_type"),
        )
        return {"ok": True, "data": {
            "episodes": [EpisodicMemoryService.to_dict(e) for e in found]
        }}
    finally:
        db.close()


async def propose_profile(context, args: dict) -> dict:
    """Narrow Operator write seam: create proposals, never canonical rows."""
    proposals = args.get("proposals") or []
    if not isinstance(proposals, list) or not proposals or len(proposals) > 50:
        return {"ok": False, "error": {"code": "invalid_arguments", "message": "1-50 proposals are required"}}
    db = _session()
    try:
        service = MemoryCandidateService(db)
        ids = []
        for spec in proposals:
            candidate_type = spec.get("candidate_type")
            if candidate_type not in ("student_record", "vault_fact"):
                raise ValueError("Only student_record and vault_fact proposals are supported")
            source_type = "document" if spec.get("file_id") else "agent"
            if spec.get("file_id"):
                from sqlalchemy import select
                from app.models import FileRecord
                owned_file = db.execute(select(FileRecord.id).where(
                    FileRecord.id == spec["file_id"],
                    FileRecord.workspace_id == context.workspace_id,
                    FileRecord.status == "active",
                )).scalar_one_or_none()
                if owned_file is None:
                    raise ValueError("Evidence file does not belong to this workspace")
            evidence = {"file_id": spec.get("file_id"), "quote": spec.get("quote")}
            evidence = {key: value for key, value in evidence.items() if value}
            candidate = service.propose(
                workspace_id=context.workspace_id, candidate_type=candidate_type,
                key=spec.get("key"), proposed_value=spec.get("value"),
                entities=spec.get("entities") or {}, confidence=float(spec.get("confidence", 0.8)),
                source_type=source_type, evidence=evidence,
            )
            ids.append(candidate.id)
        from app.runtime.task_runtime import enqueue
        job = enqueue(db,
            "memory.reconcile", {"candidate_ids": ids}, context.workspace_id,
            idempotency_key="profile-proposals:" + ":".join(ids),
        )
        db.commit()
        return {"ok": True, "data": {"proposed": len(ids), "job_id": job.id}}
    except (TypeError, ValueError) as exc:
        db.rollback()
        return {"ok": False, "error": {"code": "invalid_proposal", "message": str(exc)}}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
