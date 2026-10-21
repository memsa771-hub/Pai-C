# -*- coding: utf-8 -*-
"""PAI Counselor runtime for events addressed to the built-in counselor."""

import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import select

from app.config import config
from app.database import SessionLocal
from app.pai_c.posting import send_to_student
from app.pai_c.reliability import policy as reliability_policy, record_fallback

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
            db.rollback()
            record_fallback(db, workspace_id, event_data, "provider_fallback")
            await _post_error_message(
                workspace_id, event_data, PAI_AGENT_NAME,
                reliability_policy()["provider_error"],
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
        record_fallback(db, workspace_id, event_data, "unconfigured_fallback")
        await _post_error_message(
            workspace_id, event_data, PAI_AGENT_NAME,
            reliability_policy()["unconfigured"],
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
    safety = None
    classifier_ms = 0
    decision = signals = None
    history = None
    if turn.source.startswith("human:"):
        from app.pai_c.memory import MemoryService
        from app.inference.gateway import token_usage_turn
        from app.pai_c.policy.classifier import classify
        from app.pai_c.policy.controller import decide
        from app.pai_c.policy.state import build_state
        from app.pai_c.deep.noted_questions import NotedQuestionService
        recent = MemoryService(db).recent_turns(turn, turn.source.removeprefix("human:"),
            limit=max(4, config.PAI_COUNSELOR_HISTORY_SIZE))
        history = [{"role": row["role"], "content": row["content"]}
                   for row in recent[-config.PAI_COUNSELOR_HISTORY_SIZE:]]
        db.rollback()
        classified_at = time.monotonic()
        with token_usage_turn(turn.source_event_id):
            signals = await classify(turn.student_text, recent)
        classifier_ms = int((time.monotonic() - classified_at) * 1000)
        safety = signals.safety
        if signals.request:
            request = signals.request
            NotedQuestionService(db).record(workspace_id, turn.source_event_id, request.text,
                kind=request.kind, needs_research=request.needs_research, pending=True)
        decision = decide(build_state(db, turn, signals, recent))
        if decision.action == "clear_myth":
            from app.research.gateway import request_research
            from app.tools import ToolContext
            try:
                await request_research("myth_check", workspace_id, db=db, journey=None,
                    tool_context=ToolContext(workspace_id=workspace_id, agent_name=PAI_AGENT_NAME, api=None),
                    possibility_id=decision.topic, refresh_key=turn.source_event_id)
            except Exception as exc:
                db.rollback()
                logger.warning("myth_enqueue_failed error_type=%s", type(exc).__name__)
    flagged = decision is not None and decision.action == "care"
    fallback_reply = None
    result = None
    try:
        result = await run_deep_turn(db, turn, history=history,
            decision=decision, signals=signals,
            instructions="wellbeing" if flagged else None,
            safety_level=safety.level if flagged else None)
    except Exception as exc:
        if not flagged:
            raise
        db.rollback()
        logger.warning("wellbeing_reply_error error_type=%s", type(exc).__name__)
        fallback_reply = config.PAI_WELLBEING_FALLBACK_REPLY
        if config.PAI_WELLBEING_RESOURCES:
            fallback_reply += "\n\n" + config.PAI_WELLBEING_RESOURCES
    reply = fallback_reply if fallback_reply is not None else result.reply
    action = {"type": "wellbeing"} if flagged else result.action
    if decision is not None and not flagged and action.get("type") != "wellbeing":
        if decision.action == "mirror":
            action = {"type": "mirror"}
        elif action.get("type") == "mirror":
            action = {"type": "none"}
    context = result.context if result is not None else None
    moves = [] if fallback_reply is not None or result is None else result.moves
    violations = ["wellbeing_fallback"] if fallback_reply is not None else list(result.guard_violations) if result else []
    if signals is not None and getattr(signals, "_fallback", False):
        violations.append("classifier_fallback")
    post_started = time.monotonic()
    reply_metadata = _voice_reply_metadata(event_data)
    if decision is not None and decision.action == "discover":
        reply_metadata = {**(reply_metadata or {}), "possibility_id": decision.topic}
    if (reply_metadata and action.get("type") == "mirror"
            and context.notebook.mirror_ready):
        reply_metadata["mirror_pending"] = True
    from app.pai_c.fact_cards import validated_card, presentation_card
    card = validated_card(action, context.fact_cards, turn.student_text) if context and decision and decision.question_allowed and not flagged else None
    from app.pai_c.deep.actions import shown_place
    if place := shown_place(action):
        # The student sees a link to the place; never a route or system name.
        reply_metadata = {**(reply_metadata or {}), "workspace_place": place}
    inline_card = presentation_card(decision, safety_flagged=flagged)
    if inline_card:
        reply_metadata = {**(reply_metadata or {}), "counselor_card": inline_card}
    assistant_event_id = await send_to_student(
        db, workspace_id, turn.channel, PAI_AGENT_NAME, reply, depth,
        metadata=reply_metadata, extra_payload={"fact_card": card} if card else None,
    )
    post_ms = int((time.monotonic() - post_started) * 1000)
    if not assistant_event_id:
        return None
    if decision is not None and decision.action == "clear_myth":
        from app.pai_c.myths import record_answer
        record_answer(db, workspace_id, decision.topic, turn.source_event_id, assistant_event_id)
    if decision is not None and decision.action == "discover":
        from app.pai_c.possibilities import PossibilityService
        PossibilityService(db).mark_mentioned(workspace_id, decision.topic)
        db.commit()
    if decision is not None and decision.action in {"answer_request", "counsel"} and signals.request is not None and not signals.request.needs_research and action.get("type") != "wellbeing":
        NotedQuestionService(db).mark_answered_now(workspace_id, turn.source_event_id, assistant_event_id)
    move = "none"
    status = "none"
    try:
        move, status = await dispatch_action(db, turn, action, context, reply_event_id=assistant_event_id)
    except Exception:
        db.rollback()
        logger.exception("counselor: deep action failed after reply was posted")
        status = "failed"
    if turn.source_event_id and not db.execute(select(CounselorTurnDecision.id).where(
        CounselorTurnDecision.workspace_id == workspace_id,
        CounselorTurnDecision.source_event_id == turn.source_event_id,
    )).scalar_one_or_none():
        from app.pai_c.policy.state import decision_log
        logged_decision = decision_log(decision, signals) if decision is not None else None
        if logged_decision is not None and "statement_fallback" in violations:
            logged_decision["statement_fallback"] = True
        db.add(CounselorTurnDecision(
            workspace_id=workspace_id, source_event_id=turn.source_event_id,
            source_timestamp=turn.timestamp or int(time.time() * 1000),
            move="wellbeing" if flagged else move,
            safety_level=safety.level if safety else None,
            safety_category=safety.category if safety else None,
            moves=moves, decision=logged_decision,
            guard_violations=violations + (["action_failed"] if status == "failed" else []),
        ))
        db.commit()
    # Queue after the reply and its decision are durable: a cache hit must not
    # overtake the acknowledgment, and a Voice safety override must win.
    # Research starts whenever the student is told it will: on the policy's
    # answer_request with a research need, and equally when Voice itself noted
    # a question for research (its prompt says "I will check" and sets
    # note_question). Without the second case PAI promised a check that never
    # ran. The job is idempotent per request, so both paths queue it once.
    voice_noted = move == "note_question" and status == "recorded"
    policy_asked = (decision is not None and decision.action == "answer_request" and signals.request
                    and signals.request.needs_research)
    if (policy_asked or voice_noted) and action.get("type") != "wellbeing":
        from app.research.gateway import request_research
        from app.tools import ToolContext
        try:
            await request_research("information", workspace_id, db=db, journey=None,
                tool_context=ToolContext(workspace_id=workspace_id, agent_name=PAI_AGENT_NAME, api=None),
                refresh_key=turn.source_event_id)
        except Exception as exc:
            db.rollback()
            logger.warning("information_enqueue_failed error_type=%s", type(exc).__name__)
    # A student asking which paths they have gets them worked out in the
    # background by the path analyzer; the reply above never waits for it.
    from app.pai_c.paths.analyzer import enqueue_path_analysis, policy as path_policy
    if (signals is not None and signals.request is not None and not flagged
            and signals.request.kind in path_policy()["triggers"]["request_kinds"]):
        try:
            enqueue_path_analysis(db, workspace_id, source_event_id=turn.source_event_id,
                                  channel=turn.channel, reason="asked")
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("path_analysis_enqueue_failed error_type=%s", type(exc).__name__)
    logger.info(
        "counselor_deep_turn context_ms=%d model_ms=%d polish_ms=%d "
        "post_ms=%d classifier_ms=%d total_ms=%d action=%s action_status=%s moves=%s",
        context.build_ms if context else 0,
        result.model_ms if result is not None else 0,
        result.polish_ms if result is not None else 0, post_ms, classifier_ms,
        int((time.monotonic() - started) * 1000), move, status, moves,
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
