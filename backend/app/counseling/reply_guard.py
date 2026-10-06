"""Review collection replies against the server's turn plan before posting."""

import json
import logging

from app.config import config
from app.inference.client import chat_completion
from .turn_contract import parse_turn


logger = logging.getLogger(__name__)


def _fallback(question: str | None) -> str:
    return ("I hear what you want to work on, and I'll keep it in view. "
            + (question or "We can pick up the profile detail when it is ready."))


async def guard_collection_reply(reply: str, *, student_message: str,
                                 question: str | None) -> str:
    """Keep the visible reply inside Gate 1 without language-specific rules.

    The checker cannot mutate state. A failed or malformed check falls back to
    the registry's next question instead of releasing an unchecked draft.
    """
    try:
        raw = await chat_completion(
            api_key=config.PAI_API_KEY,
            model=config.PAI_MODEL,
            base_url=config.PAI_BASE_URL or None,
            reasoning_effort="low",
            max_tokens=700,
            system_prompt=(
                "You review a counselor reply while a student's critical profile foundation "
                "is incomplete. Return JSON only: {\"allowed\": boolean, \"reply\": string}. "
                "Allowed: acknowledge the request, general information, urgent wellbeing help, "
                "and at most one profile question. Disallowed: personalized fit conclusions, "
                "rankings, admission predictions, plans or actions based on an incomplete profile, "
                "or any internal state. If allowed, set reply to the draft unchanged. Otherwise "
                "rewrite it naturally in the student's language, keeping useful general help "
                "and asking at most the supplied next question. Never mention this review."
            ),
            messages=[{"role": "user", "content": json.dumps({
                "student_message": student_message[:4000],
                "draft": reply[:5000],
                "next_question": question,
            }, ensure_ascii=False)}],
        )
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if not isinstance(result, dict) or not isinstance(result.get("allowed"), bool):
            raise ValueError("Invalid collection review")
        candidate = result.get("reply")
        if result["allowed"]:
            return reply
        if isinstance(candidate, str) and candidate.strip():
            visible, _ = parse_turn(candidate)
            if visible and visible == candidate.strip():
                return visible
    except Exception:
        logger.warning("counselor: collection reply review unavailable", exc_info=True)
    return _fallback(question)
