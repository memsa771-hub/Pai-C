"""Conversation evidence required before a parked goal becomes a Journey."""

import json
import logging

from sqlalchemy import select

from app.config import config
from app.inference.client import chat_completion
from app.models import EventRecord
from app.journey.service import JourneyService
from app.memory.student_records import StudentRecordService
from app.memory.extraction_context import _is_workspace_owner_source


logger = logging.getLogger(__name__)


def previous_route_review(db, workspace_id: str, channel: str,
                          before_timestamp: int | None, counselor_name: str) -> tuple[str, str] | None:
    """Read the immediately preceding chat reply, in this student's channel."""
    if before_timestamp is None:
        return None
    rows = db.execute(select(EventRecord).where(
        EventRecord.network_id == workspace_id,
        EventRecord.target == channel,
        EventRecord.type == "workspace.message.posted",
        EventRecord.timestamp < before_timestamp,
    ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc()).limit(20)).scalars()
    for row in rows:
        if (row.payload or {}).get("message_type", "chat") not in {"chat", "operator_result"}:
            continue
        if row.source != f"openagents:{counselor_name}":
            return None
        marker = (row.metadata_ or {}).get("route_reviewed_goal_id")
        return (marker, (row.payload or {}).get("content", "")) if isinstance(marker, str) else None
    return None


async def _judge(system_prompt: str, data: dict) -> bool:
    try:
        raw = await chat_completion(
            api_key=config.PAI_API_KEY, model=config.PAI_MODEL,
            base_url=config.PAI_BASE_URL or None,
            reasoning_effort="low", max_tokens=160,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": json.dumps(data, ensure_ascii=False, default=str)}],
        )
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        return isinstance(parsed, dict) and parsed.get("yes") is True
    except Exception:
        logger.warning("counselor: goal transition review unavailable", exc_info=True)
        return False


async def reviewed_route(reply: str, *, goal_title: str, known_context: dict) -> bool:
    """A route review must explain evidence, uncertainty and alternatives."""
    return await _judge(
        "Check whether the counselor's visible reply discusses this specific student goal "
        "against the supplied known context, states at least one material gap or uncertainty, "
        "offers a plausible way to close it or an alternative preserving the student's "
        "objective, and invites the student's choice. Do not infer facts absent from the "
        "context. Return only JSON: {\"yes\": true|false}. Any ambiguity is false.",
        {"goal": goal_title, "known_context": known_context, "reply": reply[:5000]},
    )


async def confirms_reviewed_route(student_message: str, *, goal_title: str,
                                  previous_reply: str) -> bool:
    """Require an explicit, unambiguous owner confirmation of that route."""
    return await _judge(
        "Check whether the student explicitly chooses to pursue the supplied goal after "
        "the immediately preceding counselor reply. A question, hypothetical, thanks, "
        "acknowledgment of a different point, or conditional interest is not confirmation. "
        "Interpret any language. Return only JSON: {\"yes\": true|false}. "
        "Any ambiguity is false.",
        {"goal": goal_title, "previous_reply": previous_reply[:2500],
         "student_message": student_message[:4000]},
    )


async def resolve_or_activate_goal(db, workspace_id: str, event_data: dict,
                                   counselor_name: str, foundation_ready: bool):
    """Return the active Journey, creating one only after reviewed owner consent."""
    if not foundation_ready:
        return None
    journeys = JourneyService(db)
    current = journeys.resolve_active(workspace_id)
    if current is not None:
        return current
    event_id = event_data.get("id")
    owner_event = db.get(EventRecord, event_id) if event_id else None
    channel = event_data.get("target")
    if (owner_event is None or owner_event.network_id != workspace_id
            or owner_event.target != channel
            or not _is_workspace_owner_source(db, workspace_id, owner_event.source)):
        return None
    try:
        boundary = int(event_data.get("timestamp"))
    except (TypeError, ValueError):
        return None
    reviewed = previous_route_review(db, workspace_id, channel, boundary, counselor_name)
    if reviewed is None:
        return None
    goal_id, previous_reply = reviewed
    goal = StudentRecordService(db).get(workspace_id, "goal", goal_id)
    if goal is None:
        return None
    from .turn_semantics import classify_turn
    semantics = await classify_turn(
        (event_data.get("payload") or {}).get("content", ""),
        previous_assistant=previous_reply,
    )
    intent = semantics.get("journey_intent") or {}
    if intent.get("action") != "upsert":
        return None
    if not await confirms_reviewed_route(
            (event_data.get("payload") or {}).get("content", ""),
            goal_title=goal.title, previous_reply=previous_reply):
        return None
    try:
        result = journeys.create(
            workspace_id, intent["journey_type"], goal.title,
            primary=True, actor=owner_event.source,
            current_stage="ALIGNING", current_objective=goal.title,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        logger.warning("counselor: confirmed goal could not start Journey", exc_info=True)
        return journeys.resolve_active(workspace_id)
