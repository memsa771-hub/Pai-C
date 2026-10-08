"""One fast Counselor model call, with a single language-repair exception."""

import json
import logging
import re
import time
from dataclasses import dataclass

from app.config import config
from app.counseling.deep.context import DeepContext, build_context
from app.counseling.deep.polish import contains_devanagari, polish_reply
from app.counseling.deep.prompts import load_prompt
from app.counseling.deep.turn_input import CounselorTurnInput, shared_history
from app.inference.client import chat_completion

logger = logging.getLogger(__name__)
_ROMAN_URDU_FALLBACK = "Main aap ki baat samajh raha hoon. Aap is baare mein thora aur bata sakte hain?"
_PLAIN_FALLBACK = "I want to understand you properly. Could you tell me a little more?"
_DEVANAGARI_RETRY = "Reply again in Roman Urdu with Urdu words, no Devanagari"


@dataclass(frozen=True)
class DeepTurnResult:
    reply: str
    action: dict
    context: DeepContext
    model_ms: int
    polish_ms: int


def _parse_response(raw: str) -> tuple[str, dict]:
    def valid(text: str) -> tuple[str, dict] | None:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("reply"), str):
            return None
        action = parsed.get("action")
        return parsed["reply"], action if isinstance(action, dict) else {"type": "none"}

    first = valid(raw)
    if first is not None:
        return first
    unfenced = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.IGNORECASE).strip()
    second = valid(unfenced)
    if second is not None:
        return second
    # Do not display malformed JSON or internal action keys to the student.
    stripped = raw.strip()
    if stripped.startswith(("{", "[", "```")) or not stripped:
        return _PLAIN_FALLBACK, {"type": "none"}
    return stripped, {"type": "none"}


async def run_deep_turn(db, turn: CounselorTurnInput) -> DeepTurnResult:
    context = await build_context(db, turn.workspace_id, turn)
    owner_id = turn.source.removeprefix("human:") if turn.source.startswith("human:") else ""
    history = [{"role": item["role"], "content": item["content"]}
               for item in shared_history(db, turn, owner_id, limit=20)]
    current = turn.student_text.strip() or "I attached a document."
    messages = [{"role": "user", "content": context.text}, *history,
                {"role": "user", "content": current}]
    # Read transactions must not remain open over the network call.
    db.rollback()
    prompt = load_prompt("counselor")
    started = time.monotonic()
    raw = await chat_completion(
        api_key=config.PAI_API_KEY, model=config.PAI_COUNSELOR_MODEL,
        messages=messages, system_prompt=prompt,
        response_format={"type": "json_object"},
        reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
        base_url=config.PAI_BASE_URL,
    )
    model_ms = int((time.monotonic() - started) * 1000)
    polish_started = time.monotonic()
    reply, action = _parse_response(raw)
    reply = polish_reply(reply)
    if contains_devanagari(reply):
        initial_polish_ms = int((time.monotonic() - polish_started) * 1000)
        retry_started = time.monotonic()
        retried = await chat_completion(
            api_key=config.PAI_API_KEY, model=config.PAI_COUNSELOR_MODEL,
            messages=messages, system_prompt=prompt + "\n" + _DEVANAGARI_RETRY,
            response_format={"type": "json_object"},
            reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
            base_url=config.PAI_BASE_URL,
        )
        model_ms += int((time.monotonic() - retry_started) * 1000)
        polish_started = time.monotonic()
        reply, action = _parse_response(retried)
        reply = polish_reply(reply)
        if contains_devanagari(reply):
            reply, action = _ROMAN_URDU_FALLBACK, {"type": "none"}
    else:
        initial_polish_ms = 0
    if not reply:
        reply, action = _PLAIN_FALLBACK, {"type": "none"}
    return DeepTurnResult(reply, action, context, model_ms,
                          initial_polish_ms + int((time.monotonic() - polish_started) * 1000))
