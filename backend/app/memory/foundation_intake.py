"""Foreground capture of student profile claims before a Counselor reply.

The ordinary background extraction still learns the full durable turn. This
bounded pass only reconciles canonical profile claims, so the next question is
selected from the student's answer rather than yesterday's snapshot.
"""

import logging

from .candidates import MemoryCandidateService
from .extraction_context import build_turn_context
from .extractor import extract_candidates
from .field_definitions import ENTITY_BACKED_LEGACY_FIELDS, VaultFieldDefinitionService
from .reconciler import MemoryReconciler


logger = logging.getLogger(__name__)


async def capture_foundation_turn(db, workspace_id: str, event_data: dict) -> bool:
    event_id = event_data.get("id")
    if not event_id:
        return False
    turn = build_turn_context(
        db, workspace_id, event_id, channel=event_data.get("target"))
    if turn is None or turn.is_empty():
        return False
    definitions = [
        row for row in VaultFieldDefinitionService(db).list_definitions()
        if row.key not in ENTITY_BACKED_LEGACY_FIELDS
    ]
    fields = [{"key": row.key, "data_type": row.data_type,
               "description": row.description, "validation_schema": row.validation_schema}
              for row in definitions]
    try:
        extracted = await extract_candidates(turn, {row.key for row in definitions}, fields)
        candidates = MemoryCandidateService(db)
        reconciler = MemoryReconciler(db)
        metadata = event_data.get("metadata") or {}
        input_channel = "voice" if isinstance(metadata, dict) and metadata.get("voice_delegation_id") else "conversation"
        for item in extracted:
            # Goal statements are saved as exploratory profile records, never
            # promoted to an active Journey by this intake path.
            if item.candidate_type not in {"student_record", "vault_fact"}:
                continue
            candidate = candidates.propose(
                workspace_id=workspace_id,
                candidate_type=item.candidate_type,
                operation=item.operation,
                key=item.key,
                proposed_value=item.proposed_value,
                entities=item.entities,
                confidence=item.confidence,
                source_type="conversation",
                input_channel=input_channel,
                source_event_ids=[turn.user_event_id],
                evidence=item.evidence,
            )
            reconciler.reconcile(candidate)
        db.commit()
        # The background job still extracts semantic and episodic memories,
        # but need not propose these same canonical claims a second time.
        return True
    except Exception:
        db.rollback()
        logger.warning("foundation intake unavailable; background extraction remains queued",
                       exc_info=True)
        return False
