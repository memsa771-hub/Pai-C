"""Validate and record model-requested Counselor actions without model calls."""

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from app.config import config
from app.counseling.deep.context import DeepContext
from app.counseling.deep.turn_input import CounselorTurnInput
from app.models import EventRecord, Roadmap, Workspace

logger = logging.getLogger(__name__)
_KNOWN = frozenset({"none", "mirror", "ask_research", "wellbeing", "rethink"})


def _record(db, turn: CounselorTurnInput, name: str, status: str, **details) -> None:
    db.add(EventRecord(
        id=str(uuid4()), network_id=turn.workspace_id,
        type=f"counselor.action.{name}", source="openagents:pai",
        target=turn.channel, payload={"status": status, **details},
        metadata_={"trigger_event_id": turn.source_event_id},
        timestamp=int(time.time() * 1000), visibility="private",
    ))
    db.commit()


async def _research(db, turn: CounselorTurnInput, context: DeepContext, question: str) -> str:
    if not question or len(question) > 500:
        _record(db, turn, "ask_research", "ignored", reason="invalid_question")
        return "ignored"
    workspace = db.execute(select(Workspace).where(
        Workspace.id == turn.workspace_id, Workspace.status == "active",
    ).with_for_update()).scalar_one_or_none()
    if workspace is None:
        db.rollback()
        return "ignored"
    prior = db.execute(select(EventRecord.id).where(
        EventRecord.network_id == turn.workspace_id,
        EventRecord.type == "counselor.action.ask_research",
        EventRecord.metadata_["trigger_event_id"].as_string() == turn.source_event_id,
    ).limit(1)).scalar_one_or_none()
    if prior:
        db.rollback()
        return "duplicate"
    now = datetime.now(timezone.utc)
    start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    used = db.scalar(select(func.count()).select_from(EventRecord).where(
        EventRecord.network_id == turn.workspace_id,
        EventRecord.type == "counselor.action.ask_research",
        EventRecord.timestamp >= start_ms,
        EventRecord.payload["status"].as_string().in_(("pending", "accepted")),
    )) or 0
    if used >= config.PAI_COUNSELOR_RESEARCH_DAILY_LIMIT:
        _record(db, turn, "ask_research", "ignored", reason="daily_limit")
        return "rate_limited"
    # Reserve the daily slot while the workspace row is locked, then release
    # the transaction before Operator opens its own database session.
    owner_id, password_hash = workspace.owner_user_id, workspace.password_hash
    reservation_id = str(uuid4())
    db.add(EventRecord(
        id=reservation_id, network_id=turn.workspace_id,
        type="counselor.action.ask_research", source="openagents:pai",
        target=turn.channel, payload={"status": "pending"},
        metadata_={"trigger_event_id": turn.source_event_id},
        timestamp=int(time.time() * 1000), visibility="private",
    ))
    db.commit()
    from app.memory.permissions import capabilities_for_agent
    from app.services.pai import PAI_AGENT_NAME, WorkspaceApi
    from app.tools import AUDIENCE_COUNSELOR, ToolContext, get_tool_executor

    ctx = ToolContext(
        workspace_id=turn.workspace_id, agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(turn.workspace_id, password_hash),
        conversation=turn.channel.removeprefix("channel/"),
        user_id=owner_id,
        allowed_tools=frozenset({"operator.delegate"}),
        audience=AUDIENCE_COUNSELOR,
        granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
    )
    try:
        result = await get_tool_executor().execute("operator.delegate", {
            "objective": f"Research this one student question using official sources: {question}",
            "task_type": "question_research", "intent": "academic_planning",
            "constraints": {"journey_id": context.journey.id if context.journey else None,
                            "question_event_id": turn.source_event_id},
            "context_refs": ["vault", "memory"],
        }, ctx)
    except Exception:
        logger.exception("counselor: question research delegation failed")
        result = {"ok": False}
    accepted = isinstance(result, dict) and result.get("ok") is True
    reservation = db.get(EventRecord, reservation_id)
    reservation.payload = {"status": "accepted" if accepted else "failed",
                           "run_id": ((result.get("data") or {}).get("run_id")
                                      if accepted else None)}
    db.commit()
    return "accepted" if accepted else "failed"


async def dispatch_action(db, turn: CounselorTurnInput, action: dict,
                          context: DeepContext) -> tuple[str, str]:
    kind = action.get("type") if isinstance(action, dict) else None
    if not isinstance(kind, str) or kind not in _KNOWN:
        logger.warning("counselor: unknown deep action type=%s", str(kind)[:40])
        return "none", "ignored"
    if kind == "none":
        return kind, "none"
    if kind == "mirror":
        ready = bool(context.notebook.mirror_ready)
        logger.info("counselor: mirror requested ready=%s", ready)
        _record(db, turn, kind, "requested" if ready else "ignored",
                reason=None if ready else "not_ready")
        return kind, "requested" if ready else "ignored"
    if kind == "ask_research":
        question = action.get("research_question") or action.get("question")
        return kind, await _research(db, turn, context,
                                     question.strip() if isinstance(question, str) else "")
    if kind == "wellbeing":
        _record(db, turn, kind, "recorded")
        return kind, "recorded"
    rows = db.execute(select(Roadmap).where(
        Roadmap.workspace_id == turn.workspace_id,
        Roadmap.journey_id == (context.journey.id if context.journey else ""),
    ).order_by(Roadmap.created_at.desc()).limit(1)).scalars().all()
    if not rows:
        _record(db, turn, kind, "ignored", reason="no_roadmaps")
        return kind, "ignored"
    from app.journey import JourneyService
    from app.roadmaps.service import RoadmapError, RoadmapService

    try:
        stage = context.journey.current_stage
        if stage == "PROPOSED":
            RoadmapService(db).rethink(turn.workspace_id, rows[0].id)
        elif stage == "CHOSEN":
            JourneyService(db).set_counselor_stage(
                turn.workspace_id, context.journey.id, "DIRECTION",
                actor="openagents:pai", replan_escalation=True,
            )
        else:
            _record(db, turn, kind, "ignored", reason="stage_not_replannable")
            return kind, "ignored"
    except (RoadmapError, ValueError):
        db.rollback()
        _record(db, turn, kind, "ignored", reason="replan_unavailable")
        return kind, "ignored"
    _record(db, turn, kind, "accepted")
    return kind, "accepted"
