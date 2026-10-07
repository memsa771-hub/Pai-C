"""One Counselor turn for text, final voice transcripts and check-ins."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Awaitable

from sqlalchemy import select

from app.config import config
from app.models import CounselorTurnDecision, EventRecord, StudentJourney, User, Workspace
from app.memory.student_snapshot import StudentSnapshotService
from app.journey import JourneyService
from .extraction import TurnExtraction, extract_turn
from .move import CounselorMove, plan_move
from .scope import classify_scope
from .slot_capture import capture_turn_slots
from .slots import CounselorSlotRegistry, SlotState, next_open_slot
from .summary import has_correction, is_explicit_confirmation, summary_payload
from .understanding import StudentUnderstandingBuilder

logger = logging.getLogger(__name__)


async def _timed(stage: str, event_id: str, work):
    started = time.monotonic()
    try:
        return await work
    finally:
        logger.info("counselor span event=%s stage=%s duration_ms=%d",
                    event_id, stage, round((time.monotonic() - started) * 1000))


@dataclass(frozen=True)
class CounselorTurnInput:
    channel: str  # delivery/logging only; not supplied to planner, models or guard
    workspace_id: str
    student_text: str
    attachments: tuple[dict, ...]
    session_id: str | None
    source_event_id: str
    timestamp: int | None
    source: str
    voice: bool = False


def shared_history(db, turn: CounselorTurnInput, owner_id: str,
                   *, limit: int = 24) -> list[dict]:
    """Student and PAI chat across channels in this workspace, causally prior."""
    query = select(EventRecord).where(
        EventRecord.network_id == turn.workspace_id,
        EventRecord.type == "workspace.message.posted",
        EventRecord.source.in_((f"human:{owner_id}", "openagents:pai")),
    )
    if turn.timestamp is not None:
        query = query.where(EventRecord.timestamp < turn.timestamp)
    else:
        query = query.where(EventRecord.id != turn.source_event_id)
    rows = db.execute(query.order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
                      .limit(limit * 3)).scalars().all()
    history = []
    for row in rows:
        payload = row.payload or {}
        text = payload.get("content")
        if (payload.get("message_type", "chat") != "chat" or not isinstance(text, str)
                or not text.strip() or text.startswith("[Error]")):
            continue
        history.append({"role": "assistant" if row.source == "openagents:pai" else "user",
                        "content": text[:1500], "target": row.target,
                        "session_id": (row.metadata_ or {}).get("voice_session_id")
                        or (row.metadata_ or {}).get("session_id")})
        if len(history) == limit:
            break
    history.reverse()
    return history


def _returning(history: list[dict], turn: CounselorTurnInput) -> bool:
    students = [row for row in history if row["role"] == "user"]
    if not students:
        return False
    return bool(students[-1]["target"] != turn.channel or (
        turn.session_id and students[-1].get("session_id")
        and students[-1]["session_id"] != turn.session_id))


def _facts(states: dict[str, SlotState]) -> dict:
    return {key: state.value for key, state in states.items()
            if state.status in {"answered", "pending"} and state.value is not None}


def _last_planned_slot(db, turn: CounselorTurnInput) -> str | None:
    query = select(CounselorTurnDecision).where(
        CounselorTurnDecision.workspace_id == turn.workspace_id)
    if turn.timestamp is not None:
        query = query.where(CounselorTurnDecision.source_timestamp < turn.timestamp)
    row = db.execute(query.order_by(CounselorTurnDecision.source_timestamp.desc(),
                                     CounselorTurnDecision.id.desc())
                     .limit(1)).scalar_one_or_none()
    value = (row.slot_key or ("goal_summary_confirmed"
            if row.move == "summarize_for_confirmation" else None)) if row else None
    return value if isinstance(value, str) else None


def _reflect(extraction: TurnExtraction | None, states: dict[str, SlotState],
             returning: bool) -> tuple[str, ...]:
    def concise(key, value):
        if isinstance(value, dict):
            if key == "stated_goal":
                return str(value.get("title") or "")
            if key == "recent_qualification":
                return str(value.get("qualification_name") or "")
            if key == "budget":
                return " ".join(str(value.get(part) or "") for part in ("amount", "currency", "period")).strip()
        return str(value)
    if returning:
        return tuple(concise(key, states[key].value) for key in
                     ("stated_goal", "recent_qualification", "budget")
                     if key in states and states[key].value is not None)[:2]
    return tuple(concise(claim.key, claim.value)
                 for claim in (extraction.claims if extraction else ())[:2])


async def run_counselor_turn(
    db, turn: CounselorTurnInput,
    *, writer: Callable[..., Awaitable[str]] | None = None,
    guard: Callable[..., Awaitable[tuple[str, tuple[str, ...]]]] | None = None,
) -> tuple[CounselorMove, str, tuple[str, ...]]:
    """Return one approved reply; caller handles only output delivery."""
    if not turn.student_text.strip() and not turn.attachments:
        raise ValueError("Empty Counselor turn")
    workspace = db.get(Workspace, turn.workspace_id)
    if workspace is None or not workspace.owner_user_id:
        raise ValueError("Student workspace not found")
    owner = db.get(User, workspace.owner_user_id)
    history = shared_history(db, turn, str(workspace.owner_user_id))
    snapshots = StudentSnapshotService(db)
    snapshot = snapshots.build(turn.workspace_id)
    registry = CounselorSlotRegistry(db)
    requirements = registry.active()
    states = registry.states(turn.workspace_id, snapshot, before_timestamp=turn.timestamp)
    known = _facts(states)
    expected_slot = _last_planned_slot(db, turn)
    existing_journey = db.execute(select(StudentJourney).where(
        StudentJourney.workspace_id == turn.workspace_id,
        StudentJourney.journey_type == "counselor_decision",
        StudentJourney.status == "active",
    )).scalar_one_or_none()
    awaiting_summary = bool(existing_journey and
                            (existing_journey.counselor_summary_draft or {}).get("status")
                            == "awaiting_confirmation")
    human = turn.source.startswith("human:")
    if human and turn.student_text.strip():
        scope, extraction = await asyncio.gather(
            _timed("scope", turn.source_event_id,
                   classify_scope(turn.student_text, history)),
            _timed("extraction", turn.source_event_id,
                   extract_turn(turn.student_text, history, requirements, known,
                                awaiting_summary=awaiting_summary,
                                expected_slot=expected_slot)),
        )
        capture_extraction = extraction
        if awaiting_summary and extraction.summary_response == "confirmed":
            capture_extraction = replace(
                extraction, claims=tuple(claim for claim in extraction.claims
                                         if claim.key == "goal_summary_confirmed"),
                unknown_or_declined=(), response_statuses=())
        capture_turn_slots(db, turn.workspace_id, turn.source_event_id,
                           capture_extraction, requirements, snapshot,
                           channel="voice" if turn.voice else "conversation")
        db.commit()
        snapshot = snapshots.build(turn.workspace_id)
        states = registry.states(turn.workspace_id, snapshot, before_timestamp=turn.timestamp)
    else:
        scope, extraction = "in_scope", None

    journeys = JourneyService(db)
    journey = journeys.ensure_counselor(turn.workspace_id, actor="openagents:pai")
    if journey.current_stage == "IDENTITY" and owner and owner.onboarded_at:
        journey = journeys.set_counselor_stage(turn.workspace_id, journey.id,
                                                "FOUNDATION", actor="openagents:pai")
    if (journey.current_stage == "FOUNDATION"
            and next_open_slot(requirements, states, snapshot, "foundation") is None):
        journey = journeys.set_counselor_stage(turn.workspace_id, journey.id,
                                                "DIRECTION", actor="openagents:pai")
    db.commit()
    returning = _returning(history, turn)
    draft = journey.counselor_summary_draft
    from .student_requests import StudentRequestService
    request_service = StudentRequestService(db)
    open_request = (request_service.oldest_open(turn.workspace_id)
                    if journey.current_stage == "NEEDS_INFO" else None)
    correction = has_correction(extraction, draft)
    confirmed = is_explicit_confirmation(extraction, draft) and not correction
    awaiting = bool(draft and draft.get("status") == "awaiting_confirmation" and not correction)
    planner_started = time.monotonic()
    move = plan_move(
        stage=journey.current_stage, requirements=requirements, states=states,
        snapshot=snapshot, scope=scope,
        student_question=extraction.student_question if extraction else "",
        emotion=extraction.emotion if extraction else "none",
        language=extraction.language if extraction else "en",
        returning=returning and not correction,
        reflected_facts=_reflect(extraction, states, returning),
        awaiting_confirmation=awaiting, confirmed=confirmed,
        first_turn=not history and not (extraction and extraction.claims),
        open_request=request_service.serialize(open_request) if open_request else None,
        replanning=(journey.next_recommended_action or {}).get("type") == "replan_discussion",
    )
    logger.info("counselor span event=%s stage=planner duration_ms=%d",
                turn.source_event_id, round((time.monotonic() - planner_started) * 1000))
    understanding = StudentUnderstandingBuilder(db).build(turn.workspace_id, snapshot=snapshot)
    if writer is None:
        from .writer import write_move
        writer = write_move
    if guard is None:
        from .guard_v2 import approve_reply
        guard = approve_reply
    reply = await _timed("writer", turn.source_event_id, writer(
        move=move, student_text=turn.student_text,
        history=history, understanding=understanding,
        states=states, requirements=requirements))
    approved, violations = await _timed("guard", turn.source_event_id, guard(
        reply=reply, move=move, student_text=turn.student_text,
        states=states, requirements=requirements,
        writer=writer, history=history, understanding=understanding,
    ))
    logger.info("counselor v2 turn=%s move=%s stage=%s slot=%s guard=%s",
                turn.source_event_id, move.type, move.stage, move.slot_key,
                ",".join(violations) or "pass")
    db.add(CounselorTurnDecision(
        id=str(uuid.uuid4()), workspace_id=turn.workspace_id,
        source_event_id=turn.source_event_id,
        source_timestamp=turn.timestamp if turn.timestamp is not None else int(time.time() * 1000),
        move=move.type, slot_key=move.slot_key,
        guard_violations=list(violations),
    ))
    if move.type == "summarize_for_confirmation":
        from .guard_v2 import fallback_reply
        if approved != fallback_reply(move, requirements):
            journeys.set_counselor_summary(
                turn.workspace_id, journey.id, summary_payload(states, extraction),
                approved, turn.source_event_id)
    elif move.type == "confirm_and_queue_research":
        journeys.queue_counselor_research(turn.workspace_id, journey.id,
                                          turn.source_event_id)
    elif move.type == "ask_research_request" and open_request:
        request_service.mark_asked(open_request)
    elif move.type == "replan_discussion":
        journey_row = db.get(StudentJourney, journey.id)
        journey_row.next_recommended_action = None
    return move, approved, violations
