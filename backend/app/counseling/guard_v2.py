"""Check a drafted Counselor reply and retry once before a safe fallback."""

import json
import logging
import re

from app.config import config
from app.inference.client import chat_completion
from .slots import short_key

logger = logging.getLogger(__name__)

_OPENER = re.compile(r"^(?:great|nice|good|absolutely|solid|strong base)\b", re.I)
_LIST = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
_QUESTION_FORMS = re.compile(r"\b(?:kya|kyun|kab|kaise|kaun|kis|kitna|kitni)\b|(?:کیا|کیوں|کب|کیسے|کون|کس|کتنا|کتنی)", re.I)
_LIST_REQUEST = re.compile(r"\b(?:list|bullet points|several options|options ki list)\b|فہرست", re.I)
_TEMPLATES = {
    "en": "I hear you.", "roman_ur": "Main samajh raha hoon.",
    "ur": "میں آپ کی بات سمجھ رہا ہوں۔", "mixed": "Main samajh raha hoon.",
}


def _question_count(reply: str) -> int:
    punctuation = reply.count("?") + reply.count("؟")
    if punctuation:
        return punctuation
    # A question in Urdu or Roman Urdu may omit punctuation.
    return 1 if _QUESTION_FORMS.search(reply) else 0


def deterministic_violations(reply: str, move, states, requirements,
                             *, student_asked_for_list: bool = False) -> tuple[str, ...]:
    problems = []
    text = reply.strip()
    questions = _question_count(text)
    if questions > 1:
        problems.append("more_than_one_question")
    if questions and not (text.endswith("?") or text.endswith("؟")):
        problems.append("question_not_last")
    if len(text.split()) > move.max_words:
        problems.append("word_limit")
    if _OPENER.match(text):
        problems.append("praise_or_filler_opener")
    if _LIST.search(text) and not student_asked_for_list:
        problems.append("unrequested_list")
    if move.slot_key and states.get(move.slot_key) and states[move.slot_key].answered:
        problems.append("answered_slot_question")
    if move.slot_key and questions == 0:
        problems.append("missing_planned_question")
    if not move.slot_key and move.type in {"crisis", "wellbeing", "confirm_and_queue_research"} and questions:
        problems.append("unexpected_question")
    has_urdu = bool(re.search(r"[\u0600-\u06ff]", text))
    if move.language == "ur" and not has_urdu:
        problems.append("language_mismatch")
    if move.language in {"en", "roman_ur"} and has_urdu:
        problems.append("language_mismatch")
    return tuple(problems)


async def model_violations(reply: str, move, student_text: str,
                           states: dict) -> tuple[str, ...]:
    schema = {"type": "object", "properties": {
        key: {"type": "boolean"} for key in (
            "verdict", "unsourced_fact", "off_goal", "lecture", "wrong_slot", "wrong_language")
    }, "required": ["verdict", "unsourced_fact", "off_goal", "lecture",
                     "wrong_slot", "wrong_language"], "additionalProperties": False}
    raw = await chat_completion(
        api_key=config.PAI_API_KEY,
        model=config.PAI_COUNSELOR_AUX_MODEL or config.PAI_MODEL,
        base_url=config.PAI_BASE_URL,
        system_prompt=(
            "Review a Counselor reply. Flag verdict if it calls a goal doable, "
            "impossible, guaranteed or gives eligibility/chances. Flag unsourced_fact "
            "for specific requirements, tests, fees, deadlines, rankings, statistics "
            "or institution facts not supplied as student facts. Flag off_goal if "
            "irrelevant to the student's education/career goal. Flag lecture if it "
            "explains more than asked. Flag wrong_slot if its question does not ask "
            "the planned slot intent. Flag wrong_language if it fails to mirror the "
            "student's language. Return booleans only."
        ),
        messages=[{"role": "user", "content": json.dumps({
            "student_text": student_text, "reply": reply,
            "move": {"type": move.type, "slot_key": move.slot_key,
                     "question_intent": move.question_intent,
                     "language": move.language},
            "known_slot_values": {key: state.value for key, state in states.items()
                                  if state.answered and state.value is not None},
        }, ensure_ascii=False, default=str)}],
        max_tokens=100,
        response_format={"type": "json_schema", "json_schema": {
            "name": "pai_counselor_reply_check", "strict": True, "schema": schema,
        }},
    )
    result = json.loads(raw)
    return tuple(key for key in schema["properties"] if result.get(key) is True)


def fallback_reply(move, requirements) -> str:
    if move.type == "crisis":
        return "I'm sorry you're going through this. If you're in immediate danger, contact local emergency services or someone you trust now."
    if move.type == "wellbeing":
        return "I'm sorry this feels difficult. We can pause and talk about what feels hardest right now."
    prefix = _TEMPLATES.get(move.language, _TEMPLATES["en"])
    if move.slot_key:
        slot = next((row for row in requirements if short_key(row) == move.slot_key), None)
        question = (slot.canonical_questions or {}).get(move.language) if slot else None
        return f"{prefix} {question}" if question else prefix
    if move.type == "summarize_for_confirmation":
        return {"en": "Have I understood your goal correctly?",
                "ur": "کیا میں نے آپ کا مقصد درست سمجھا ہے؟",
                "roman_ur": "Kya main ne aap ka maqsad sahi samjha hai?",
                "mixed": "Kya main ne aap ka maqsad sahi samjha hai?"}[move.language]
    if move.type == "confirm_and_queue_research":
        return {"en": "I’ll look into routes that fit your goal, including other ways to reach it.",
                "ur": "میں آپ کے مقصد کے مطابق راستے دیکھوں گا، اور اسے حاصل کرنے کے دوسرے طریقے بھی۔",
                "roman_ur": "Main aap ke maqsad ke liye munasib raaste dekhunga, aur us tak pohanchne ke doosre tareeqe bhi.",
                "mixed": "Main aap ke goal ke liye munasib raaste dekhunga, aur alternatives bhi."}[move.language]
    return prefix


async def approve_reply(*, reply, move, student_text, states, requirements,
                        writer, history, understanding) -> tuple[str, tuple[str, ...]]:
    """Check, rewrite once with exact violations, then deterministic fallback."""
    violations_seen = []
    current = reply.strip()
    for attempt in range(2):
        violations = list(deterministic_violations(current, move, states, requirements,
                            student_asked_for_list=bool(_LIST_REQUEST.search(student_text))))
        try:
            violations += await model_violations(current, move, student_text, states)
        except Exception:
            logger.warning("counselor reply model check unavailable", exc_info=True)
            violations.append("model_check_unavailable")
        if not violations:
            return current, tuple(violations_seen)
        violations_seen.extend(dict.fromkeys(violations))
        if attempt == 0:
            current = (await writer(move=move, student_text=student_text,
                                    history=history, understanding=understanding,
                                    states=states, requirements=requirements,
                                    violations=tuple(violations))).strip()
    logger.warning("counselor reply guard fallback: violations=%s", violations_seen)
    return fallback_reply(move, requirements), tuple(dict.fromkeys(violations_seen))
