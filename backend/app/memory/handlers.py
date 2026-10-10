# -*- coding: utf-8 -*-
"""Durable job handlers for memory formation.

Registered centrally as system capabilities before the worker starts claiming.

Why these run here and not in the chat path: extraction calls an LLM and
reconciliation touches several tables. Doing that inline would add seconds to
every reply, which requirement #3 forbids. The conversation completes, a job is
enqueued, and memory catches up a moment later.

Phase 1 deliberately ships extraction as a **no-op stub**: the pipeline,
durability and reconciliation are real and tested end to end, but the LLM
extraction prompt is Phase 2. A stub that records "nothing extracted" is honest;
a half-tuned prompt silently writing wrong facts is not.
"""

import logging
from sqlalchemy import select

from app.memory.candidates import MemoryCandidateService
from app.memory.index import MemoryRecord, get_memory_index
from app.memory.reconciler import MemoryReconciler
from app.memory.semantic import MemoryService
from app.models import EventRecord, PaiEpisode, PaiMemory

logger = logging.getLogger(__name__)

JOB_EXTRACT = "memory.extract"
JOB_RECONCILE = "memory.reconcile"
JOB_EMBED = "memory.embed"
JOB_UNINDEX = "memory.unindex"
JOB_REINDEX = "memory.reindex"
def _is_duplicate(db, workspace_id: str, item) -> bool:
    """Already-known memory/episode? Vault handles its own conflicts.

    A Vault fact is never skipped here: "my CGPA is 3.52" restated is harmless
    (the reconciler retains the existing row), and a *correction* must always
    reach the reconciler.
    """
    from app.memory.dedupe import is_duplicate_episode, is_duplicate_memory

    if item.candidate_type == "semantic_memory":
        return is_duplicate_memory(
            db, workspace_id,
            (item.entities or {}).get("memory_type", "context"),
            item.content or "",
        )
    if item.candidate_type == "episode":
        return is_duplicate_episode(
            db, workspace_id,
            (item.entities or {}).get("event_type", ""),
            item.content or "",
        )
    return False


async def extract_memory(job, db) -> dict:
    """Propose memory candidates from a conversation slice.

    Phase 2 replaces the body with an extraction prompt. The contract is fixed
    now: this function may ONLY write candidates. It has no access to
    VaultService, so even a buggy future prompt cannot mutate canonical state.
    """
    workspace_id = job.workspace_id
    payload = job.payload or {}
    if not workspace_id:
        raise ValueError("memory.extract requires a workspace_id")

    candidates = MemoryCandidateService(db)
    proposed = []

    # The source type is decided HERE, from the job's declared origin — never
    # read from the per-candidate spec, because in Phase 2 that spec is model
    # output. `memory.extract` jobs are enqueued with the channel they read
    # ("conversation" for chat, "document" for an uploaded file), and every
    # candidate from this job inherits it.
    #
    # `user_explicit` is unreachable from here by construction: it is refused
    # unless the caller passes `allow_user_explicit`, which only the explicit
    # remember/forget tools do.
    source_type = payload.get("source_type") or "conversation"
    if source_type not in ("conversation", "document", "agent", "system"):
        raise ValueError(f"memory.extract: untrusted source_type {source_type!r}")

    # Path A — pre-parsed proposals. Used by tests and by any caller that has
    # already decided what to propose.
    for spec in payload.get("candidates") or []:
        candidate = candidates.propose(
            workspace_id=workspace_id,
            candidate_type=spec.get("candidate_type", "semantic_memory"),
            operation=spec.get("operation", "upsert"),
            key=spec.get("key"),
            proposed_value=spec.get("proposed_value"),
            content=spec.get("content"),
            entities=spec.get("entities"),
            confidence=float(spec.get("confidence", 0.5)),
            source_type=source_type,
            source_event_ids=spec.get("source_event_ids"),
            evidence=spec.get("evidence"),
        )
        proposed.append(candidate.id)

    # Path B — extract from a persisted conversational turn. The payload holds
    # only IDs; the source events are read back from PostgreSQL here.
    user_event_id = payload.get("user_event_id")
    types_proposed: list[str] = []
    if not proposed and user_event_id:
        from app.memory.extraction_context import build_turn_context
        from app.memory.extractor import extract_candidates
        from app.memory.field_definitions import VaultFieldDefinitionService

        turn = build_turn_context(
            db, workspace_id=workspace_id, user_event_id=user_event_id,
            assistant_event_id=payload.get("assistant_event_id"),
            channel=payload.get("channel"),
        )
        if turn is None:
            # The source event is gone (workspace deleted, event purged).
            # Nothing to extract and nothing to retry — succeed quietly.
            logger.info(
                "memory.extract: source turn missing job=%s workspace=%s user_event=%s",
                job.id, workspace_id, user_event_id,
            )
            return {"candidates_proposed": 0, "reason": "source_turn_missing"}

        definitions = VaultFieldDefinitionService(db).list_definitions()
        from app.memory.field_definitions import ENTITY_BACKED_LEGACY_FIELDS
        definitions = [d for d in definitions if d.key not in ENTITY_BACKED_LEGACY_FIELDS]
        allowed_keys = {d.key for d in definitions}
        # The same set twice, for two different jobs: `allowed_keys` is the
        # authorization filter, `field_specs` is what the model is actually
        # shown so it can name those keys exactly (see extractor._render_field_specs).
        field_specs = [
            {
                "key": d.key,
                "data_type": d.data_type,
                "description": d.description,
                "validation_schema": d.validation_schema,
            }
            for d in definitions
        ]
        # ExtractionError propagates: malformed model output fails the job so
        # the durable worker retries it, rather than writing half-trusted rows.
        extracted = await extract_candidates(turn, allowed_keys, field_specs)
        source_event = db.execute(select(EventRecord).where(
            EventRecord.id == turn.user_event_id,
            EventRecord.network_id == workspace_id,
        )).scalar_one_or_none()
        source_metadata = source_event.metadata_ if source_event else None
        input_channel = "voice" if isinstance(source_metadata, dict) and source_metadata.get("voice_delegation_id") else "conversation"

        for item in extracted:
            if payload.get("profile_captured") and item.candidate_type in {"vault_fact", "student_record"}:
                continue
            if _is_duplicate(db, workspace_id, item):
                logger.info(
                    "memory.extract: skipped duplicate %s job=%s", item.candidate_type, job.id
                )
                continue
            candidate = candidates.propose(
                workspace_id=workspace_id,
                candidate_type=item.candidate_type,
                operation=item.operation,
                key=item.key,
                proposed_value=item.proposed_value,
                content=item.content,
                entities=item.entities,
                confidence=item.confidence,
                # Server-assigned. The extractor has no field for this and
                # cannot reach `user_explicit` — `propose()` refuses it without
                # `allow_user_explicit`, which this path never passes.
                source_type=source_type,
                input_channel=input_channel,
                # EVIDENCE — the student's event only. The assistant reply is
                # context for resolving references, never a factual source; a
                # memory attributed to it would let PAI's own words become
                # student truth via the provenance trail.
                source_event_ids=[turn.user_event_id],
                # The assistant event stays reachable for debugging ("what was
                # PAI saying when this was extracted?") but as context, clearly
                # separated from what evidences the claim.
                evidence={
                    **item.evidence,
                    **({"context_assistant_event_id": turn.assistant_event_id}
                       if turn.assistant_event_id else {}),
                },
            )
            proposed.append(candidate.id)
            types_proposed.append(item.candidate_type)

    logger.info(
        "memory.extract: job=%s workspace=%s user_event=%s assistant_event=%s "
        "proposed=%d types=%s",
        job.id, workspace_id, user_event_id, payload.get("assistant_event_id"),
        len(proposed), sorted(set(types_proposed)) or None,
    )

    # Chain reconciliation as its own durable job rather than calling it here:
    # if reconciliation fails it retries on its own schedule without re-running
    # extraction, and each job stays independently observable.
    if proposed:
        from app.runtime.task_runtime import enqueue

        enqueue(db,
            job_type=JOB_RECONCILE,
            workspace_id=workspace_id,
            payload={"candidate_ids": proposed},
            idempotency_key=f"reconcile:{job.id}",
        )

    return {"candidates_proposed": len(proposed)}


async def reconcile_memory(job, db) -> dict:
    """Run the deterministic reconciler over pending candidates."""
    workspace_id = job.workspace_id
    if not workspace_id:
        raise ValueError("memory.reconcile requires a workspace_id")

    reconciler = MemoryReconciler(db)
    payload = job.payload or {}
    candidate_ids = payload.get("candidate_ids")

    results = []
    if candidate_ids:
        service = MemoryCandidateService(db)
        for candidate_id in candidate_ids:
            candidate = service.get(workspace_id, candidate_id)
            if candidate is not None:
                results.append(reconciler.reconcile(candidate))
    else:
        results = reconciler.reconcile_pending(workspace_id)

    accepted = [r for r in results if r.accepted]

    # Indexing is deliberately NOT done here. It calls an external provider,
    # so it fails on a different schedule from reconciliation — and an
    # embedding outage must never roll back canonical memory that was
    # correctly reconciled. Instead we enqueue a separate durable job, in this
    # same transaction: if the commit succeeds both the memory and its embed
    # job exist; if it fails, neither does.
    #
    # The idempotency key is derived from the memory ids, so a retried
    # reconcile job cannot queue the same embedding work twice.
    # Accepted facts/records queue indexing in the reconciler, including direct calls.
    from app.config import config
    embed_count = sum(bool(result.result_id) and
                      MemoryCandidateService(db).get(workspace_id, result.candidate_id).candidate_type
                      in {"vault_fact", "student_record"} for result in accepted) if config.PAI_SEMANTIC_RECALL_ENABLED else 0

    # A document's candidates are now decided: let the document pipeline tell
    # the student what actually happened. Enqueued in this transaction, so the
    # message job exists exactly when the decisions it reports are committed.
    if payload.get("document_file_id"):
        from app.documents.handlers import enqueue_document_notify

        enqueue_document_notify(db, workspace_id, payload["document_file_id"])

    return {
        "reconciled": len(results),
        "accepted": len(accepted),
        "rejected": len(results) - len(accepted),
        "embed_enqueued": embed_count,
    }


async def embed_memory(job, db) -> dict:
    """Push accepted facts/records and session summaries into the retrieval index.

    Separate from reconciliation because embedding is the part that calls an
    external provider and therefore fails differently — it deserves its own
    retry schedule rather than dragging a successful reconciliation down with
    it.

    Only `active` rows are indexed. A row that was forgotten between
    reconciliation and this job simply never enters the index.
    """
    workspace_id = job.workspace_id
    if not workspace_id:
        raise ValueError("memory.embed requires a workspace_id")

    from app.config import config
    if not config.PAI_SEMANTIC_RECALL_ENABLED:
        return {"indexed": 0, "reason": "disabled"}
    payload = job.payload or {}
    records = _records_for(
        db, workspace_id,
        memory_ids=payload.get("memory_ids") or [],
        episode_ids=payload.get("episode_ids") or [],
        fact_ids=payload.get("fact_ids") or [],
        record_refs=payload.get("record_refs") or [],
    )

    indexed = await get_memory_index().index(records) if records else 0
    logger.info(
        "memory.embed: job=%s workspace=%s requested=%d indexed=%d",
        job.id, workspace_id,
        sum(len(payload.get(key) or []) for key in ("memory_ids", "episode_ids", "fact_ids", "record_refs")),
        indexed,
    )
    return {"indexed": indexed}


def _records_for(db, workspace_id: str, memory_ids: list, episode_ids: list,
                 fact_ids=None, record_refs=None) -> list:
    """Only canonical accepted facts/records and session summaries get new vectors."""
    from app.models import VaultFact
    from app.memory.student_records import ENTITY_MODELS
    from app.memory.index_sources import canonical_text
    records = []
    for fact_id in fact_ids or []:
        row = db.scalar(select(VaultFact).where(VaultFact.workspace_id == workspace_id,
            VaultFact.id == fact_id, VaultFact.status == "active"))
        if row is not None:
            records.append(MemoryRecord(id=row.id, workspace_id=workspace_id, kind="vault_fact",
                text=canonical_text(row, "vault_fact"), filters={"status": "active"}))
    for ref in record_refs or []:
        model = ENTITY_MODELS.get(ref.get("kind"))
        if model is None:
            continue
        row = db.scalar(select(model).where(model.workspace_id == workspace_id,
            model.id == ref.get("id"), model.status == "active"))
        if row is not None:
            kind = "student_record:" + ref["kind"]
            records.append(MemoryRecord(id=row.id, workspace_id=workspace_id, kind=kind,
                text=canonical_text(row, kind), filters={"status": "active"}))
    for episode_id in episode_ids:
        row = db.scalar(select(PaiEpisode).where(PaiEpisode.workspace_id == workspace_id,
            PaiEpisode.id == episode_id, PaiEpisode.status == "active",
            PaiEpisode.event_type == "session_summary"))
        if row is not None:
            records.append(MemoryRecord(id=row.id, workspace_id=workspace_id, kind="episode",
                text=row.summary, filters={"event_type": "session_summary", "status": "active"}))
    return records


async def unindex_memory(job, db) -> dict:
    """Remove ids from the retrieval index (forgotten/superseded rows).

    Correctness does NOT depend on this landing: `MemoryRetriever` re-reads
    PostgreSQL and drops anything inactive, so a delayed or failed deletion
    cannot resurface a forgotten memory. This just keeps the index tidy.
    """
    workspace_id = job.workspace_id
    if not workspace_id:
        raise ValueError("memory.unindex requires a workspace_id")

    ids = (job.payload or {}).get("ids") or []
    deleted = await get_memory_index().delete(workspace_id, ids) if ids else 0
    logger.info(
        "memory.unindex: job=%s workspace=%s deleted=%d", job.id, workspace_id, deleted
    )
    return {"deleted": deleted}


async def reindex_workspace(job, db) -> dict:
    """Rebuild one workspace's index from PostgreSQL.

    The recovery path: Qdrant lost, collection dropped, or the embedding model
    changed. Canonical data is untouched, so this is always safe to re-run.
    """
    from app.config import config
    from app.models import VaultFact
    from app.memory.student_records import ENTITY_MODELS
    workspace_id = job.workspace_id
    if not workspace_id:
        raise ValueError("memory.reindex requires a workspace_id")
    if not config.PAI_SEMANTIC_RECALL_ENABLED:
        return {"indexed": 0, "reason": "disabled"}
    index = get_memory_index()
    payload = job.payload or {}
    if payload.get("purge_first") and hasattr(index, "drop_workspace"):
        await index.drop_workspace(workspace_id)
    batch_size = max(1, int(payload.get("batch_size") or 64))
    total = facts = records_count = episodes = 0
    for batch in _iter_ids(db, workspace_id, VaultFact, batch_size):
        facts += len(batch)
        total += await index.index(_records_for(db, workspace_id, [], [], fact_ids=batch))
    for kind, model in ENTITY_MODELS.items():
        for batch in _iter_ids(db, workspace_id, model, batch_size):
            records_count += len(batch)
            total += await index.index(_records_for(db, workspace_id, [], [],
                record_refs=[{"kind": kind, "id": item} for item in batch]))
    for batch in _iter_ids(db, workspace_id, PaiEpisode, batch_size):
        records = _records_for(db, workspace_id, [], batch)
        episodes += len(records)
        if records:
            total += await index.index(records)
    return {"indexed": total, "facts": facts, "records": records_count,
            "memories": 0, "episodes": episodes}


def _iter_ids(db, workspace_id: str, model, batch_size: int):
    """Yield batches of active row ids, keyset-paginated by primary key.

    Keyset rather than OFFSET: a concurrent insert during a long rebuild
    shifts OFFSET windows and makes rows get skipped or repeated. Memory use
    stays bounded at one batch of ids regardless of table size.
    """
    from sqlalchemy import select

    last_id = ""
    while True:
        batch = list(db.execute(
            select(model.id).where(
                model.workspace_id == workspace_id,
                model.status == "active",
                model.id > last_id,
            ).order_by(model.id).limit(batch_size)
        ).scalars().all())
        if not batch:
            return
        yield batch
        last_id = batch[-1]


