# -*- coding: utf-8 -*-
"""PAI Counselor runtime for events addressed to the built-in counselor."""

import logging
import time
from typing import Optional

from sqlalchemy import select

from app.config import config
from app.database import SessionLocal
from app.pai_c.posting import send_to_student

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
    posted = await _run_deep_turn(db, workspace_id, event_data, depth)
    if posted and str(event_data.get("source") or "").startswith("human:"):
        from app.pai_c.memory import MemoryService
        from app.services.pai import PAI_AGENT_NAME

        assistant_event_id, channel_target = posted
        MemoryService(db).enqueue_turn_extraction(
            workspace_id=workspace_id, channel_target=channel_target,
            user_event_id=event_data.get("id"),
            assistant_event_id=assistant_event_id,
            agent_name=PAI_AGENT_NAME,
        )
        from app.pai_c.deep.analysis import enqueue_turn_analysis

        enqueue_turn_analysis(db, workspace_id, event_data.get("id"), assistant_event_id)


async def _run_deep_turn(db, workspace_id: str, event_data: dict, depth: int):
    """One deep Counselor response, posted through the shared chat/voice path."""
    from app.pai_c.deep.actions import dispatch_action
    from app.pai_c.deep.turn import run_deep_turn
    from app.pai_c.deep.turn_input import CounselorTurnInput
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
    from app.pai_c.deep.polish import question_count

    if (question_count(result.reply) == 0
            and result.action.get("type") not in {"mirror", "wellbeing"}):
        logger.info("reply_without_question turn_id=%s", turn.source_event_id)
    post_started = time.monotonic()
    reply_metadata = _voice_reply_metadata(event_data)
    if (reply_metadata and result.action.get("type") == "mirror"
            and result.context.notebook.mirror_ready):
        reply_metadata["mirror_pending"] = True
    assistant_event_id = await send_to_student(
        db, workspace_id, turn.channel, PAI_AGENT_NAME, result.reply, depth,
        metadata=reply_metadata,
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
    return assistant_event_id, turn.channel


def _event_order_boundary(event_data: dict) -> Optional[int]:
    """Best-effort extraction of the triggering event's timestamp (unix ms)."""
    try:
        return int(event_data.get("timestamp"))
    except (TypeError, ValueError):
        return None


async def _post_error_message(
    workspace_id: str, event_data: dict, agent_name: str, error_text: str,
) -> None:
    """Post an error message to the channel on behalf of the Counselor.

    Opens its own short-lived DB session so a stale connection from a
    long-running API call cannot prevent the error from reaching the user.
    """
    err_db = SessionLocal()
    try:
        await send_to_student(
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
