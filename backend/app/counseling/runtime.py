# -*- coding: utf-8 -*-
"""PAI Counselor runtime for events addressed to the built-in counselor."""

import asyncio
import json as _json
import logging
from typing import Optional

from sqlalchemy import select

from app.config import config
from app.database import SessionLocal
from app.models import EventRecord

logger = logging.getLogger(__name__)


def _voice_reply_metadata(event_data: dict) -> Optional[dict]:
    metadata = event_data.get("metadata") or {}
    delegation_id = metadata.get("voice_delegation_id") if isinstance(metadata, dict) else None
    if isinstance(delegation_id, str) and 0 < len(delegation_id) <= 128:
        return {"voice_delegation_id": delegation_id}
    return None

async def run_counselor(workspace_id: str, event_data: dict) -> None:
    """Handle one event when its target is the first-party PAI Counselor."""
    from app.services.pai import PAI_AGENT_NAME

    metadata = event_data.get("metadata") or {}
    target_agents = metadata.get("target_agents") or []
    if PAI_AGENT_NAME not in target_agents:
        return

    depth = metadata.get("counselor_depth", 0)
    if depth >= config.PAI_COUNSELOR_MAX_DEPTH:
        logger.warning("counselor: max depth %d reached, skipping", depth)
        return

    db = SessionLocal()
    try:
        try:
            await _run_turn(db, workspace_id, event_data, depth)
        except Exception as exc:
            logger.error(
                "counselor: invocation failed: error_type=%s status=%s",
                type(exc).__name__, getattr(exc, "status_code", None) or "unknown",
            )
            await _post_error_message(
                workspace_id, event_data, PAI_AGENT_NAME,
                "PAI Counselor could not reach the language service right now. "
                "Please try again shortly.",
            )
    finally:
        db.close()


async def _run_turn(db, workspace_id: str, event_data: dict, depth: int) -> None:
    """Answer through the shared natural-text Core, then queue quiet learning."""
    from app.services.pai import PAI_AGENT_NAME
    from app.documents.attachments import (
        describe_attachments, normalize_attachments,
        wait_until_readable,
    )
    from app.memory.student_snapshot import StudentSnapshotService
    from app.memory.profile_completion import ProfileCompletionService
    from app.memory.foreground import build_foreground_context
    from .core import CounselorCore
    from .understanding import StudentUnderstandingBuilder
    from .turn_plan import TurnPlan

    if not config.PAI_API_KEY:
        await _post_error_message(
            workspace_id, event_data, PAI_AGENT_NAME,
            "This assistant isn't configured on the server yet (missing key).",
        )
        return

    channel_target = event_data.get("target", "")
    content = event_data.get("payload", {}).get("content", "")
    attachments = normalize_attachments(
        event_data.get("payload", {}).get("attachments"))
    if not content and not attachments:
        return

    recent_conversation = _build_conversation_context(
        db, workspace_id, channel_target, PAI_AGENT_NAME,
        exclude_event_id=event_data.get("id"),
        before_timestamp=_event_order_boundary(event_data),
    )
    attachment_context = ""
    if attachments:
        await wait_until_readable(
            db, workspace_id, [item["file_id"] for item in attachments])
        try:
            described = describe_attachments(db, workspace_id, attachments)
        except Exception:
            logger.warning("counselor: attachment status unavailable", exc_info=True)
            db.rollback()
            described = attachments
        attachment_context = _json.dumps([
            {"filename": item.get("filename"), "status": item.get("processing_status")}
            for item in described
        ], ensure_ascii=False)

    completion_service = ProfileCompletionService(db)
    snapshot = StudentSnapshotService(db).build(workspace_id)
    completion = completion_service.evaluate(workspace_id, snapshot=snapshot)
    profile_captured = False
    if (completion["enforced"] and content
            and str(event_data.get("source", "")).startswith("human:")):
        from app.memory.foundation_intake import capture_foundation_turn
        profile_captured = await capture_foundation_turn(db, workspace_id, event_data)
        snapshot = StudentSnapshotService(db).build(workspace_id)
        completion = completion_service.evaluate(workspace_id, snapshot=snapshot)
    from .goal_transition import resolve_or_activate_goal
    active_journey = await resolve_or_activate_goal(
        db, workspace_id, event_data, PAI_AGENT_NAME,
        foundation_ready=bool(completion.get("enforced") and completion.get("foundationReady")),
    )
    turn_plan = TurnPlan.from_completion(completion, snapshot, active_journey)
    understanding = StudentUnderstandingBuilder(db).build(
        workspace_id, snapshot=snapshot)
    db.rollback()

    memory_context = None
    if config.PAI_MEMORY_CONTEXT_ENABLED and content:
        try:
            memory_context = await build_foreground_context(
                workspace_id=workspace_id, query=content,
                caller=PAI_AGENT_NAME,
            )
        except Exception:
            logger.warning("counselor: memory retrieval unavailable", exc_info=True)

    logger.info("counselor: invoking core (%s), %d context messages",
                config.PAI_MODEL, len(recent_conversation))
    reply = await CounselorCore().respond(
        student_message=content or "I attached a file.",
        recent_conversation=recent_conversation,
        understanding=understanding,
        memory_context=memory_context,
        attachment_context=attachment_context,
        turn_plan=turn_plan,
    )
    if turn_plan.mode == "collecting":
        from .reply_guard import guard_collection_reply
        reply = await guard_collection_reply(
            reply, student_message=content or "I attached a file.",
            question=turn_plan.question,
        )
    response_metadata = _voice_reply_metadata(event_data) or {}
    if (turn_plan.mode == "open" and turn_plan.parked_goal
            and active_journey is None
            and str(event_data.get("source", "")).startswith("human:")):
        from .context_projection import compact_student_context
        from .goal_transition import reviewed_route
        goal_row = next((row for row in snapshot.records.get("goal", [])
                         if row.get("title") == turn_plan.parked_goal), None)
        if goal_row and await reviewed_route(
                reply, goal_title=turn_plan.parked_goal,
                known_context=compact_student_context(understanding, turn_plan.parked_goal)):
            response_metadata["route_reviewed_goal_id"] = goal_row["id"]
    assistant_event_id = await _post_response(
        db, workspace_id, channel_target, PAI_AGENT_NAME, reply, depth,
        metadata=response_metadata or None,
    )
    logger.info(
        "counselor: turn_plan mode=%s foundation=%d/%d question_key=%s posted=%s",
        turn_plan.mode, *turn_plan.progress,
        (completion.get("nextRequirement") or {}).get("key"),
        bool(assistant_event_id),
    )
    # Scheduled review instructions are system events, not new student claims.
    # Keep the ordinary candidate/reconciliation learning path for real human
    # turns while preventing a routine prompt from becoming Vault evidence.
    if assistant_event_id and str(event_data.get("source", "")).startswith("human:"):
        from app.memory.turn_hook import enqueue_turn_extraction
        enqueue_turn_extraction(
            db=db, workspace_id=workspace_id, channel_target=channel_target,
            user_event_id=event_data.get("id"),
            assistant_event_id=assistant_event_id,
            agent_name=PAI_AGENT_NAME,
            profile_captured=profile_captured,
        )

def _event_order_boundary(event_data: dict) -> Optional[int]:
    """Best-effort extraction of the triggering event's timestamp (unix ms)."""
    try:
        return int(event_data.get("timestamp"))
    except (TypeError, ValueError):
        return None


def _student_context_query(messages: list[dict], current: str,
                           *, turn_semantics: dict | None = None) -> str:
    """Use the owner message as retrieval evidence; semantic intent is separate."""
    return current


def _build_conversation_context(
    db, workspace_id: str, channel_target: str, agent_name: str,
    exclude_event_id: Optional[str] = None,
    before_timestamp: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> list[dict]:
    """Fetch recent messages from the channel as conversation context.

    Only events causally prior to the trigger are eligible. When
    before_timestamp is given, rows at or after it are excluded in SQL, so
    a message committed after the trigger can never leak into this request
    and get answered early. Events carry no ordering finer than the unix-ms
    timestamp, so rows sharing the trigger's millisecond are conservatively
    dropped too. Without a boundary, the newest row is assumed to be the
    trigger and skipped (legacy behavior); exclude_event_id is a further
    guard for the id-only case.

    Chat messages are collected newest-first in pages until the window
    holds max_messages of them, the character budget is spent, or the scan
    cap is reached â€” non-chat rows (status/thinking/todos/anything else)
    never consume window slots. The character budget bounds prompt size for
    models with small context windows, which a message count alone does not.

    The scan cap makes this best-effort, deliberately: without it a busy
    channel would degrade into an unbounded table scan. If the most recent
    max_scanned rows are all noise, older chat history is invisible for
    this turn â€” a warning is logged when that happens.
    """
    max_messages = config.PAI_COUNSELOR_MAX_CONTEXT_MESSAGES
    if max_chars is None:
        max_chars = config.PAI_COUNSELOR_MAX_CONTEXT_CHARS

    batch_size = max(max_messages * 3, 100)
    max_scanned = batch_size * 10

    collected: list[dict] = []  # newest -> oldest
    used_chars = 0
    offset = 0
    drop_newest = exclude_event_id is None and before_timestamp is None

    while len(collected) < max_messages and offset < max_scanned:
        query = select(EventRecord).where(
            EventRecord.network_id == workspace_id,
            EventRecord.target == channel_target,
            EventRecord.type == "workspace.message.posted",
        )
        if before_timestamp is not None:
            query = query.where(EventRecord.timestamp < before_timestamp)

        rows = db.execute(
            query.order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
            .offset(offset)
            .limit(batch_size)
        ).scalars().all()
        if not rows:
            break

        done = False
        for row in rows:
            if drop_newest:
                drop_newest = False
                continue
            if exclude_event_id is not None and row.id == exclude_event_id:
                continue

            payload = row.payload or {}
            message_type = payload.get("message_type", "chat")
            if message_type != "chat" and not (
                message_type == "operator_result" and row.source == f"openagents:{agent_name}"
            ):
                continue
            content = payload.get("content", "")
            if not content:
                continue

            source = row.source or ""
            if source == f"openagents:{agent_name}":
                from app.counseling.turn_contract import is_counselor_fallback
                if is_counselor_fallback(content):
                    continue
            if source == f"openagents:{agent_name}":
                role = "assistant"
            elif source.startswith("human:") or source.startswith("openagents:"):
                role = "user"
            else:
                continue

            if used_chars + len(content) > max_chars:
                # Keep at least a truncated newest message so the model
                # is never invoked with the trigger's context fully empty.
                if not collected and max_chars > 0:
                    collected.append({"role": role, "content": content[:max_chars]})
                done = True
                break

            collected.append({"role": role, "content": content})
            used_chars += len(content)
            if len(collected) >= max_messages:
                done = True
                break

        if done or len(rows) < batch_size:
            break
        offset += batch_size

    if len(collected) < max_messages and offset >= max_scanned:
        logger.warning(
            "counselor: context scan cap (%d rows) reached for %s in %s "
            "with only %d chat message(s) collected â€” older history, if any, "
            "is invisible this turn",
            max_scanned, agent_name, channel_target, len(collected),
        )

    collected.reverse()
    return collected


async def _post_response(
    db, workspace_id: str, channel_target: str, agent_name: str,
    content: str, depth: int,
    attachments: Optional[list] = None,
    message_type: str = "chat",
    metadata: Optional[dict] = None,
) -> Optional[str]:
    """Post the Counselor's response through the event pipeline.

    ``message_type``/``metadata`` let a caller other than an ordinary chat
    turn attribute its post distinctly â€” e.g. PAI Operator auto-posting a
    finished run's result uses ``message_type="operator_result"`` plus
    ``{"execution_run_id", "execution_status"}`` (see
    ``operator._post_result``) so the frontend can render it as an Operator
    execution result rather than an ordinary PAI Counselor reply, without
    this pipeline needing to know anything about Operator.

    Returns the persisted event id (None if the post was rejected), so callers
    that need to reference the committed turn â€” e.g. memory extraction â€” can
    do so without re-querying for it.
    """
    from app.models import Workspace
    from app.eventing.factory import pipeline
    from app.eventing.events import Event
    from app.eventing.mods import EventRejected, PipelineContext

    workspace = db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    ).scalar_one_or_none()

    if not workspace:
        logger.error("counselor: workspace %s not found", workspace_id)
        return None

    payload: dict = {
        "content": content,
        "message_type": message_type,
    }
    if attachments:
        payload["attachments"] = attachments

    event = Event(
        type="workspace.message.posted",
        source=f"openagents:{agent_name}",
        target=channel_target,
        payload=payload,
        metadata={"counselor_depth": depth + 1, **(metadata or {})},
        visibility="channel",
        network=workspace_id,
    )

    context = PipelineContext(
        network_id=workspace_id,
        agent_address=event.source,
        db=db,
        workspace=workspace,
        token=workspace.password_hash,
    )

    try:
        await pipeline.process(event, context)
    except EventRejected as exc:
        logger.warning("counselor: response event rejected: %s", exc.reason)
        return None

    db.commit()

    snapshot = {
        "id": event.id,
        "type": event.type,
        "source": event.source,
        "target": event.target,
        "payload": event.payload,
        "metadata": event.metadata,
        "timestamp": event.timestamp,
    }

    # Publish to Redis so SSE clients receive the event in real-time
    try:
        from app.infrastructure import cache
        cache.publish_event(
            f"ws:{workspace_id}:events",
            _json.dumps(snapshot, default=str, separators=(",", ":")).encode(),
        )
    except Exception:
        pass

    # If this reply lands in a workflow thread, advance the run. Cloud replies
    # go through the pipeline directly (not the POST /v1/events route), so the
    # route's advance hook never sees them. advance_workflow is a no-op when the
    # channel has no active run; run it off the event loop so we don't block.
    try:
        from app.services.workflow import advance_workflow
        wf_event = {
            "target": event.target,
            "source": event.source,
            "payload": event.payload,
            "metadata": event.metadata,
        }
        asyncio.get_running_loop().run_in_executor(
            None, advance_workflow, workspace_id, wf_event,
        )
    except Exception:
        logger.warning("counselor: failed to schedule workflow advance", exc_info=True)

    # Cloud replies bypass POST /v1/events, so the route's Slack/Telegram
    # relay hook never sees them either â€” schedule it here the same way.
    try:
        from app.services.integrations import relay_for_event
        asyncio.get_running_loop().run_in_executor(
            None, relay_for_event, workspace_id, snapshot,
        )
    except Exception:
        logger.warning("counselor: failed to schedule integration relay", exc_info=True)

    # LAST. Every post-commit hook above must run before this returns â€”
    # returning early once orphaned the Redis publish, workflow advance and
    # integration relay, which cloud replies reach ONLY from here (they bypass
    # the POST /v1/events route that schedules them for everyone else).
    return event.id


async def _post_error_message(
    workspace_id: str, event_data: dict, agent_name: str, error_text: str,
) -> None:
    """Post an error message to the channel on behalf of the Counselor.

    Opens its own short-lived DB session so a stale connection from a
    long-running API call cannot prevent the error from reaching the user.
    """
    err_db = SessionLocal()
    try:
        await _post_response(
            err_db, workspace_id,
            event_data.get("target", ""),
            agent_name,
            f"[Error] {error_text}",
            depth=0,
            metadata=_voice_reply_metadata(event_data),
        )
    except Exception:
        logger.exception("counselor: failed to post error message for %s", agent_name)
    finally:
        err_db.close()
