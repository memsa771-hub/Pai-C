"""Validate and record model-requested Counselor actions without model calls."""

import logging
import time
from uuid import uuid4

from sqlalchemy import select

from app.pai_c.deep.context import DeepContext
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.models import EventRecord, Roadmap

logger = logging.getLogger(__name__)
_KNOWN = frozenset({"none", "mirror", "note_question", "wellbeing", "rethink"})


def _record(db, turn: CounselorTurnInput, name: str, status: str, **details) -> None:
    db.add(EventRecord(
        id=str(uuid4()), network_id=turn.workspace_id,
        type=f"counselor.action.{name}", source="openagents:pai",
        target=turn.channel, payload={"status": status, **details},
        metadata_={"trigger_event_id": turn.source_event_id},
        timestamp=int(time.time() * 1000), visibility="private",
    ))
    db.commit()


async def dispatch_action(db, turn: CounselorTurnInput, action: dict,
                          context: DeepContext) -> tuple[str, str]:
    kind = action.get("type") if isinstance(action, dict) else None
    if kind == "ask_research":
        kind = "note_question"
    if not isinstance(kind, str) or kind not in _KNOWN:
        logger.warning("counselor: unknown deep action type=%s", str(kind)[:40])
        return "none", "ignored"
    if kind == "none":
        return kind, "none"
    if kind == "mirror":
        ready = bool(context.notebook.mirror_ready)
        logger.info("counselor: mirror requested ready=%s", ready)
        if ready:
            from app.pai_c.deep.mirror import enqueue_mirror

            enqueue_mirror(db, turn)
        _record(db, turn, kind, "requested" if ready else "ignored",
                reason=None if ready else "not_ready")
        return kind, "requested" if ready else "ignored"
    if kind == "note_question":
        from app.pai_c.deep.noted_questions import NotedQuestionService

        question = (action.get("question_to_research") or action.get("research_question")
                    or action.get("question"))
        status = NotedQuestionService(db).record(
            turn.workspace_id, turn.source_event_id, question)
        if status == "recorded":
            _record(db, turn, kind, status)
        return kind, status
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
    from app.pai_c.roadmaps.service import RoadmapError, RoadmapService

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
