# -*- coding: utf-8 -*-
"""PAI Counselor runtime for events addressed to the built-in counselor."""

import asyncio
import json as _json
import logging
from dataclasses import replace
import time
import uuid
from typing import Optional

from sqlalchemy import select

from app.config import config
from app.database import SessionLocal
from app.inference.client import chat_completion_tools
from app.models import EventRecord, User, Workspace

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
    """Dispatch a turn, then queue learning only after a successful post."""
    if config.PAI_COUNSELOR_MODE == "deep":
        posted = await _run_deep_turn(db, workspace_id, event_data, depth)
    elif config.PAI_COUNSELOR_MODE == "legacy":
        posted = await _run_legacy_turn(db, workspace_id, event_data, depth)
    else:
        raise ValueError(f"Unsupported Counselor mode: {config.PAI_COUNSELOR_MODE}")
    if posted and str(event_data.get("source") or "").startswith("human:"):
        from app.memory.turn_hook import enqueue_turn_extraction
        from app.services.pai import PAI_AGENT_NAME

        assistant_event_id, channel_target, profile_captured = posted
        enqueue_turn_extraction(
            db=db, workspace_id=workspace_id, channel_target=channel_target,
            user_event_id=event_data.get("id"),
            assistant_event_id=assistant_event_id,
            agent_name=PAI_AGENT_NAME,
            profile_captured=profile_captured,
        )


async def _run_deep_turn(db, workspace_id: str, event_data: dict, depth: int):
    """One deep Counselor response, posted through the shared chat/voice path."""
    from app.counseling.deep.actions import dispatch_action
    from app.counseling.deep.turn import run_deep_turn
    from app.counseling.deep.turn_input import CounselorTurnInput
    from app.documents.attachments import normalize_attachments
    from app.models import CounselorTurnDecision
    from app.services.pai import PAI_AGENT_NAME

    if not config.PAI_API_KEY:
        await _post_error_message(
            workspace_id, event_data, PAI_AGENT_NAME,
            "This assistant isn't configured on the server yet (missing key).",
        )
        return None
    payload = event_data.get("payload") or {}
    content = payload.get("content") or ""
    attachments = normalize_attachments(payload.get("attachments"))
    if not content and not attachments:
        return None
    metadata = event_data.get("metadata") or {}
    turn = CounselorTurnInput(
        channel=event_data.get("target") or "", workspace_id=workspace_id,
        student_text=content, attachments=tuple(attachments),
        session_id=metadata.get("voice_session_id") or metadata.get("session_id"),
        source_event_id=event_data.get("id") or "",
        timestamp=_event_order_boundary(event_data),
        source=event_data.get("source") or "", voice=bool(metadata.get("voice_delegation_id")),
    )
    started = time.monotonic()
    result = await run_deep_turn(db, turn)
    post_started = time.monotonic()
    assistant_event_id = await _post_response(
        db, workspace_id, turn.channel, PAI_AGENT_NAME, result.reply, depth,
        metadata=_voice_reply_metadata(event_data),
    )
    post_ms = int((time.monotonic() - post_started) * 1000)
    if not assistant_event_id:
        return None
    move = "none"
    status = "none"
    try:
        move, status = await dispatch_action(db, turn, result.action, result.context)
    except Exception:
        db.rollback()
        logger.exception("counselor: deep action failed after reply was posted")
        status = "failed"
    if turn.source_event_id and not db.execute(select(CounselorTurnDecision.id).where(
        CounselorTurnDecision.workspace_id == workspace_id,
        CounselorTurnDecision.source_event_id == turn.source_event_id,
    )).scalar_one_or_none():
        db.add(CounselorTurnDecision(
            workspace_id=workspace_id, source_event_id=turn.source_event_id,
            source_timestamp=turn.timestamp or int(time.time() * 1000),
            move=move, guard_violations=[] if status != "failed" else ["action_failed"],
        ))
        db.commit()
    logger.info(
        "counselor_deep_turn context_ms=%d model_ms=%d polish_ms=%d "
        "post_ms=%d total_ms=%d action=%s action_status=%s",
        result.context.build_ms, result.model_ms, result.polish_ms, post_ms,
        int((time.monotonic() - started) * 1000), move, status,
    )
    return assistant_event_id, turn.channel, False


async def _run_legacy_turn(db, workspace_id: str, event_data: dict, depth: int):
    """The retained Counselor Core conversation path."""
    from app.services.pai import PAI_AGENT_NAME, WorkspaceApi
    from app.memory.permissions import capabilities_for_agent
    from app.tools import AUDIENCE_COUNSELOR, ToolContext
    from app.documents.attachments import (
        describe_attachments, normalize_attachments,
        wait_until_readable,
    )
    from app.memory.student_snapshot import StudentSnapshotService
    from app.memory.profile_completion import ProfileCompletionService
    from app.memory.foreground import build_foreground_context
    from .core import CounselorCore, CounselorModelProvider
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
    from app.journey import JourneyService
    from .stages import advance_discovery_stage

    journeys = JourneyService(db)
    active_journey = journeys.ensure_counselor(
        workspace_id, actor=f"openagents:{PAI_AGENT_NAME}")
    workspace = db.get(Workspace, workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace and workspace.owner_user_id else None
    active_journey = advance_discovery_stage(
        journeys, workspace_id, active_journey,
        identity_ready=bool(owner and owner.onboarded_at),
        foundation_ready=bool(completion.get("foundationReady")),
        goal_records=snapshot.records.get("goal", []),
        actor=f"openagents:{PAI_AGENT_NAME}",
    )
    db.commit()
    turn_plan = TurnPlan.from_completion(completion, snapshot, active_journey)
    understanding = StudentUnderstandingBuilder(db).build(
        workspace_id, snapshot=snapshot)
    semantics = {}
    if turn_plan.mode == "open":
        from .evaluator import CounselingEvaluator
        from .policy import CounselingPolicy
        from .turn_semantics import classify_turn

        semantics = await classify_turn(
            content or "", previous_assistant=next((
                item.get("content", "") for item in reversed(recent_conversation)
                if item.get("role") == "assistant"), ""))
        state = CounselingEvaluator().derive(
            message=content or "", vault_context=understanding,
            journey=active_journey.to_dict() if active_journey else None,
            completion=completion, recent_conversation=recent_conversation,
            active_conflict=next(iter(understanding.get("open_conflicts") or ()), None),
            turn_semantics=semantics,
        )
        decision = CounselingPolicy().decide(state)
        if turn_plan.question and active_journey.current_stage == "DIRECTION":
            decision = replace(decision, move="ASK", focus="goal discovery",
                               max_questions=1, operator_allowed=False,
                               roadmap_allowed=False)
        turn_plan = replace(turn_plan, policy=decision)
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
    tool_context = None
    if turn_plan.mode == "open":
        workspace = db.get(Workspace, workspace_id)
        if workspace is not None:
            from app.services.pai import PAI_ALLOWED_TOOLS
            allowed = set(PAI_ALLOWED_TOOLS)
            if turn_plan.policy and not turn_plan.policy.operator_allowed:
                allowed.discard("operator.delegate")
            tool_context = ToolContext(
                workspace_id=workspace_id, agent_name=PAI_AGENT_NAME,
                api=WorkspaceApi(workspace_id, workspace.password_hash),
                conversation=channel_target.removeprefix("channel/"),
                user_id=getattr(workspace, "owner_user_id", None),
                allowed_tools=frozenset(allowed),
                audience=AUDIENCE_COUNSELOR,
                granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
            )

    async def record_tool_result(name: str, result: dict) -> None:
        # Internal audit event; never publish as a chat message or include it
        # in the student's conversation context.
        serialized = _json.dumps(result, ensure_ascii=False, default=str)
        recorded = result if len(serialized) <= 12000 else {
            "truncated": True, "ok": result.get("ok")}
        db.add(EventRecord(
            id=str(uuid.uuid4()), network_id=workspace_id,
            type="counselor.tool.result", source=f"openagents:{PAI_AGENT_NAME}",
            target=channel_target,
            payload={"tool": name, "result": recorded},
            metadata_={"trigger_event_id": event_data.get("id")},
            timestamp=int(time.time() * 1000), visibility="private",
        ))
        db.commit()

    if turn_plan.mode == "open" and active_journey.current_stage == "RESEARCHING":
        from app.tools import ToolContext, AUDIENCE_COUNSELOR
        from app.services.pai import PAI_ALLOWED_TOOLS
        from .research_flow import delegate_research_if_ready
        research_context = tool_context
        if research_context is None or "operator.delegate" not in research_context.allowed_tools:
            workspace = db.get(Workspace, workspace_id)
            if workspace is not None:
                research_context = ToolContext(
                    workspace_id=workspace_id, agent_name=PAI_AGENT_NAME,
                    api=WorkspaceApi(workspace_id, workspace.password_hash),
                    conversation=channel_target.removeprefix("channel/"),
                    user_id=workspace.owner_user_id,
                    allowed_tools=frozenset({"operator.delegate"}) & frozenset(PAI_ALLOWED_TOOLS),
                    audience=AUDIENCE_COUNSELOR,
                    granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
                )
        delegated = await delegate_research_if_ready(
            db, workspace_id, active_journey, snapshot.records.get("goal", []),
            understanding, research_context)
        if delegated is not None:
            await record_tool_result("operator.delegate", delegated)

    from app.roadmaps.service import RoadmapService
    focused_roadmap = RoadmapService(db).focused(workspace_id)
    reply = await CounselorCore(CounselorModelProvider(chat_completion_tools)).respond(
        student_message=content or "I attached a file.",
        recent_conversation=recent_conversation,
        understanding=understanding,
        memory_context=memory_context,
        attachment_context=attachment_context,
        turn_plan=turn_plan,
        tool_context=tool_context,
        record_tool_result=record_tool_result if tool_context is not None else None,
        focused_roadmap=focused_roadmap,
    )
    from .reply_guard import guard_reply
    reply = await guard_reply(
        reply, student_message=content or "I attached a file.",
        mode=turn_plan.mode, question=turn_plan.question,
        max_questions=turn_plan.policy.max_questions if turn_plan.policy else 1,
        requirement_fields=completion.get("fields") or [],
        allow_long=semantics.get("requested_detail") is True
                   or semantics.get("requested_roadmap") is True,
    )
    response_metadata = _voice_reply_metadata(event_data) or {}
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
    return (assistant_event_id, channel_target, profile_captured) if assistant_event_id else None

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
