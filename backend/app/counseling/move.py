"""Pure selection of a Counselor move from already observed turn state."""

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from app.models import ProfileRequirement
from .slots import SlotState, next_open_slot, short_key


MoveType = Literal[
    "greet", "ask", "answer_then_ask", "acknowledge_then_ask",
    "redirect_then_ask", "summarize_for_confirmation",
    "confirm_and_queue_research", "returning_student", "wellbeing", "crisis",
]


@dataclass(frozen=True)
class CounselorMove:
    type: MoveType
    slot_key: str | None
    question_intent: str | None
    reflect: tuple[str, ...]
    answer_scope: str | None
    language: str
    max_words: int
    stage: str


def _next(requirements: Sequence[ProfileRequirement], states: Mapping[str, SlotState],
          snapshot: Any, stage: str) -> ProfileRequirement | None:
    return next_open_slot(requirements, states, snapshot, stage)


def plan_move(*, stage: str, requirements: Sequence[ProfileRequirement],
              states: Mapping[str, SlotState], snapshot: Any, scope: str,
              student_question: str, emotion: str, language: str,
              returning: bool = False, awaiting_confirmation: bool = False,
              confirmed: bool = False, reflected_facts: Sequence[str] = ()) -> CounselorMove:
    """Precedence is explicit; channel, models and databases cannot affect it."""
    language = language if language in {"en", "ur", "roman_ur", "mixed"} else "en"
    reflect = tuple(str(value) for value in reflected_facts if value)[:2]
    if scope in {"crisis", "wellbeing"}:
        return CounselorMove(scope, None, None, (), None, language, 60, stage)
    slot_stage = "foundation" if stage in {"IDENTITY", "FOUNDATION"} else "direction"
    slot = _next(requirements, states, snapshot, slot_stage)
    key = short_key(slot) if slot is not None else None
    intent = slot.question_intent if slot is not None else None
    if confirmed and awaiting_confirmation:
        return CounselorMove("confirm_and_queue_research", None, None, reflect,
                             None, language, 60, stage)
    if returning:
        return CounselorMove("returning_student", key, intent, reflect, None,
                             language, 60, stage)
    if scope == "off_topic":
        return CounselorMove("redirect_then_ask", key, intent, reflect, None,
                             language, 50, stage)
    if stage == "RESEARCHING":
        return CounselorMove("ask", None, None, reflect, None, language, 60, stage)
    if awaiting_confirmation:
        summary_slot = _next(requirements, states, snapshot, "summary")
        if student_question:
            return CounselorMove("answer_then_ask", short_key(summary_slot) if summary_slot else None,
                                 summary_slot.question_intent if summary_slot else None,
                                 reflect, "Answer briefly, then ask for confirmation of the summary.",
                                 language, 60, stage)
        return CounselorMove("ask", short_key(summary_slot) if summary_slot else None,
                             summary_slot.question_intent if summary_slot else None,
                             reflect, None, language, 60, stage)
    if slot is None and stage == "DIRECTION":
        return CounselorMove("summarize_for_confirmation", None, None, reflect,
                             None, language, 90, stage)
    if student_question:
        move_type = "answer_then_ask"
    elif emotion != "none":
        move_type = "acknowledge_then_ask"
    else:
        move_type = "ask"
    answer_scope = None
    if move_type == "answer_then_ask":
        answer_scope = (
            "For specific requirements, tests, fees, deadlines, chances or eligibility, "
            "say you will check official sources after learning their goal; give no figures. "
            "Otherwise answer in at most two general sentences."
        )
    return CounselorMove(move_type, key, intent, reflect, answer_scope,
                         language, 50 if move_type == "redirect_then_ask" else 60, stage)
