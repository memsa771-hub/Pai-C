"""One fast Counselor model call, with a single language-repair exception."""

import json
import logging
import re
import time
from dataclasses import dataclass

from app.config import config
from app.pai_c.deep.context import DeepContext, build_context
from app.pai_c.deep.polish import contains_blocked_script, polish_reply
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.pai_c.memory import MemoryService
from app.inference.gateway import complete as chat_completion, resolve_model

logger = logging.getLogger(__name__)


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
        return config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}
    if stripped.startswith('"'):
        try:
            decoded, end = json.JSONDecoder().raw_decode(stripped)
            if isinstance(decoded, str) and not stripped[end:].strip().strip(","):
                return decoded, {"type": "none"}
        except ValueError:
            pass
        return config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}
    # A truncated JSON string can leave an escaped closing quote and comma
    # after otherwise readable prose. Remove only that transport fragment.
    return re.sub(r'\\"\s*,?\s*$', "", stripped), {"type": "none"}


async def run_deep_turn(db, turn: CounselorTurnInput, *,
                        roadmap_id: str | None = None,
                        history: list[dict] | None = None,
                        instructions: str | None = None) -> DeepTurnResult:
    context = await build_context(db, turn.workspace_id, turn, roadmap_id=roadmap_id)
    owner_id = turn.source.removeprefix("human:") if turn.source.startswith("human:") else ""
    if history is None:
        history = [{"role": item["role"], "content": item["content"]}
                   for item in MemoryService(db).recent_turns(turn, owner_id,
                                              limit=config.PAI_COUNSELOR_HISTORY_SIZE)]
    current = turn.student_text.strip() or "I attached a document."
    messages = [*history, {"role": "user", "content": current}]
    # Read transactions must not remain open over the network call.
    db.rollback()
    prompt = load_prompt("counselor") + "\n\n" + context.text
    if instructions:
        prompt += "\n\n" + load_prompt(instructions)
    started = time.monotonic()
    raw = await chat_completion(role="counselor",
        api_key=config.PAI_API_KEY, model=resolve_model("counselor"),
        messages=messages, system_prompt=prompt,
        response_format={"type": "json_object"},
        reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
        base_url=config.PAI_BASE_URL,
        phase="counselor", turn_id=turn.source_event_id,
    )
    model_ms = int((time.monotonic() - started) * 1000)
    polish_started = time.monotonic()
    reply, action = _parse_response(raw)
    reply = polish_reply(reply)
    if contains_blocked_script(reply, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
        initial_polish_ms = int((time.monotonic() - polish_started) * 1000)
        retry_started = time.monotonic()
        retried = await chat_completion(role="counselor",
            api_key=config.PAI_API_KEY, model=resolve_model("counselor"),
            messages=messages, system_prompt=prompt + "\n\n" + load_prompt("language_retry"),
            response_format={"type": "json_object"},
            reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
            base_url=config.PAI_BASE_URL,
            phase="counselor_retry", turn_id=turn.source_event_id,
        )
        model_ms += int((time.monotonic() - retry_started) * 1000)
        polish_started = time.monotonic()
        reply, action = _parse_response(retried)
        reply = polish_reply(reply)
        if contains_blocked_script(reply, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            reply, action = config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}
    else:
        initial_polish_ms = 0
    if not reply:
        reply, action = config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}
    return DeepTurnResult(reply, action, context, model_ms,
                          initial_polish_ms + int((time.monotonic() - polish_started) * 1000))
