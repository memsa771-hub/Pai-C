"""Write words for a code-selected move; the model cannot choose the move."""

import json

from app.config import config
from app.inference.client import chat_completion
from app.services.counselor_prompt import PAI_V2_SYSTEM_PROMPT, PAI_V2_EXAMPLES
from .context_projection import compact_student_context
from .slots import short_key
from .summary import summary_payload


def _brief(move, states, requirements, student_text, history, understanding, violations=()):
    slot = next((row for row in requirements if short_key(row) == move.slot_key), None)
    examples = PAI_V2_EXAMPLES.get(move.type, ())[:2]
    return {
        "move": {"type": move.type, "slot_key": move.slot_key,
                 "question_intent": move.question_intent, "reflect": move.reflect,
                 "answer_scope": move.answer_scope, "language": move.language,
                 "max_words": move.max_words, "stage": move.stage,
                 "research_request": ({"field": move.request_field,
                                        "reason": move.question_intent}
                                       if move.request_id else None)},
        "canonical_question": (slot.canonical_questions or {}).get(move.language)
        if slot is not None else None,
        "known_student_context": compact_student_context(understanding, student_text),
        "known_slot_values": {key: state.value for key, state in states.items()
                              if state.status in {"answered", "pending"} and state.value is not None},
        "student_budget_words": states["budget"].quote
        if "budget" in states and states["budget"].quote else None,
        "recent_dialogue": [{"role": row["role"], "content": row["content"]}
                            for row in history[-6:]],
        "student_message": student_text,
        "examples": examples,
        "required_summary_elements": summary_payload(states)
        if move.type == "summarize_for_confirmation" else None,
        "revision_violations": list(violations),
    }


async def write_move(*, move, student_text, history, understanding, states,
                     requirements, violations=()) -> str:
    brief = _brief(move, states, requirements, student_text, history,
                   understanding, violations)
    model = config.PAI_COUNSELOR_WRITER_MODEL or config.PAI_MODEL
    return (await chat_completion(
        api_key=config.PAI_API_KEY, model=model,
        base_url=config.PAI_BASE_URL,
        messages=[{"role": "user", "content": json.dumps(brief, ensure_ascii=False, default=str)}],
        system_prompt=PAI_V2_SYSTEM_PROMPT,
        max_tokens=350, reasoning_effort="minimal",
        temperature=None if model.lower().startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")) else 0.3,
    )).strip()
