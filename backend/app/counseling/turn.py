"""One Counselor turn for text, final voice transcripts and check-ins."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

from sqlalchemy import select

from app.config import config
from app.models import EventRecord, User, Workspace
from app.memory.student_snapshot import StudentSnapshotService
from app.journey import JourneyService
from .extraction import TurnExtraction, extract_turn
from .move import CounselorMove, plan_move
from .scope import classify_scope
from .slot_capture import capture_turn_slots
from .slots import CounselorSlotRegistry, SlotState, next_open_slot
from .understanding import StudentUnderstandingBuilder

logger = logging.getLogger(__name__)


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
                        "session_id": (row.metadata_ or {}).get("session_id")})
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


def _reflect(extraction: TurnExtraction | None, states: dict[str, SlotState],
             returning: bool) -> tuple[str, ...]:
    if returning:
        return tuple(str(states[key].value) for key in
                     ("stated_goal", "recent_qualification", "budget")
                     if key in states and states[key].value is not None)[:2]
    return tuple(str(claim.value) for claim in (extraction.claims if extraction else ())[:2])


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
    human = turn.source.startswith("human:")
    if human and turn.student_text.strip():
        scope, extraction = await asyncio.gather(
            classify_scope(turn.student_text, history),
            extract_turn(turn.student_text, history, requirements, known),
        )
        capture_turn_slots(db, turn.workspace_id, turn.source_event_id,
                           extraction, requirements, snapshot,
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
    move = plan_move(
        stage=journey.current_stage, requirements=requirements, states=states,
        snapshot=snapshot, scope=scope,
        student_question=extraction.student_question if extraction else "",
        emotion=extraction.emotion if extraction else "none",
        language=extraction.language if extraction else "en",
        returning=returning, reflected_facts=_reflect(extraction, states, returning),
    )
    understanding = StudentUnderstandingBuilder(db).build(turn.workspace_id, snapshot=snapshot)
    if writer is None:
        from .writer import write_move
        writer = write_move
    if guard is None:
        from .guard_v2 import approve_reply
        guard = approve_reply
    reply = await writer(move=move, student_text=turn.student_text,
                         history=history, understanding=understanding,
                         states=states, requirements=requirements)
    approved, violations = await guard(
        reply=reply, move=move, student_text=turn.student_text,
        states=states, requirements=requirements,
        writer=writer, history=history, understanding=understanding,
    )
    logger.info("counselor v2 turn=%s move=%s stage=%s slot=%s guard=%s",
                turn.source_event_id, move.type, move.stage, move.slot_key,
                ",".join(violations) or "pass")
    return move, approved, violations
