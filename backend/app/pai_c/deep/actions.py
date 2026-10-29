"""Validate and record model-requested Counselor actions without model calls."""

import logging
import time
from uuid import uuid4

from app.pai_c.deep.context import DeepContext
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.models import EventRecord

logger = logging.getLogger(__name__)
_KNOWN = frozenset({"none", "mirror", "note_question", "wellbeing", "rethink", "collect_fact", "show_place"})


def workspace_places() -> dict[str, str]:
    from app.pai_c.policy.controller import load_data
    return load_data("workspace_places.json")["places"]


def shown_place(action: dict) -> str | None:
    """The workspace place a reply links to, only when it is a known one."""
    place = action.get("place") if isinstance(action, dict) and action.get("type") == "show_place" else None
    return place if isinstance(place, str) and place in workspace_places() else None


def _record(db, turn: CounselorTurnInput, name: str, status: str, **details) -> None:
    db.add(EventRecord(
        id=str(uuid4()), network_id=turn.workspace_id,
        type=f"counselor.action.{name}", source="openagents:pai",
        target=turn.channel, payload={"status": status, **details},
        metadata_={"trigger_event_id": turn.source_event_id},
        timestamp=int(time.time() * 1000), visibility="private",
    ))
    db.commit()


async def _post_mirror_card(db, turn: CounselorTurnInput) -> tuple[str, str | None]:
    """The ready Mirror goes into chat once, as a `counselor_mirror` card
    (header, unknowns, text, version) after the voice's one short line. It
    asks nothing; the student opens the Mirror page from it (spec 2.5)."""
    from app.journey import JourneyService
    from app.pai_c.mirror import MirrorEngine
    from app.pai_c.mirror.engine import mirror_policy
    from app.pai_c.posting import send_to_student
    from app.services.pai import PAI_AGENT_NAME

    journey = JourneyService(db).ensure_counselor(turn.workspace_id)
    draft = journey.counselor_summary_draft or {}
    if draft.get("type") == "mirror_state" and draft.get("mirror_posted_version"):
        return "ignored", "already_posted"
    card = MirrorEngine(db).build(turn.workspace_id)
    if not card["ready"]:
        return "ignored", "not_ready"
    text = card["text"]
    content = " ".join(text["sentences"]) if text else mirror_policy()["copy"]["chat_card"]
    posted = await send_to_student(
        db, turn.workspace_id, turn.channel, PAI_AGENT_NAME, content, 0, message_type="counselor_mirror",
        extra_payload={key: card[key] for key in ("header", "unknowns", "text", "version")},
        metadata={"mirror_card_version": card["version"]})
    if not posted:
        return "failed", "not_posted"
    JourneyService(db).note_mirror_posted(turn.workspace_id, card["version"])
    db.commit()
    return "posted", None


async def dispatch_action(db, turn: CounselorTurnInput, action: dict,
                          context: DeepContext, *, reply_event_id: str | None = None) -> tuple[str, str]:
    kind = action.get("type") if isinstance(action, dict) else None
    if kind == "ask_research":
        kind = "note_question"
    if not isinstance(kind, str) or kind not in _KNOWN:
        logger.warning("counselor: unknown deep action type=%s", str(kind)[:40])
        return "none", "ignored"
    if kind == "none":
        return kind, "none"
    if kind == "collect_fact":
        from app.pai_c.fact_cards import validated_card
        status = "offered" if validated_card(action, context.fact_cards, turn.student_text) else "ignored"
        _record(db, turn, kind, status)
        return kind, status
    if kind == "show_place":
        status = "offered" if shown_place(action) else "ignored"
        _record(db, turn, kind, status)
        return kind, status
    if kind == "mirror":
        status, reason = await _post_mirror_card(db, turn)
        logger.info("counselor: mirror card status=%s", status)
        _record(db, turn, kind, status, reason=reason)
        return kind, status
    if kind == "note_question":
        from app.pai_c.deep.noted_questions import NotedQuestionService, request_policy

        question = (action.get("question_to_research") or action.get("research_question")
                    or action.get("question"))
        policy = request_policy()
        status = NotedQuestionService(db).record(
            turn.workspace_id, turn.source_event_id, question,
            kind=action.get("kind", policy["default_kind"]),
            needs_research=action.get("needs_research", policy["default_needs_research"]),
            answered_event_id=reply_event_id)
        if status == "recorded":
            _record(db, turn, kind, status)
        return kind, status
    if kind == "wellbeing":
        _record(db, turn, kind, "recorded")
        return kind, "recorded"
    # "rethink" moves only the journey stage back to direction; it never
    # touches the student's chosen route (that changes only on the Roadmap page).
    from app.journey import JourneyService

    stage = context.journey.current_stage if context.journey else None
    if stage not in {"PROPOSED", "CHOSEN"}:
        _record(db, turn, kind, "ignored", reason="stage_not_replannable")
        return kind, "ignored"
    try:
        JourneyService(db).set_counselor_stage(
            turn.workspace_id, context.journey.id, "DIRECTION",
            actor="openagents:pai", replan_escalation=stage == "CHOSEN",
        )
    except ValueError:
        db.rollback()
        _record(db, turn, kind, "ignored", reason="replan_unavailable")
        return kind, "ignored"
    _record(db, turn, kind, "accepted")
    return kind, "accepted"
