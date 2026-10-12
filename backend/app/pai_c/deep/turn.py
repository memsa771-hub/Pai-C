"""One fast Counselor model call, with bounded language and repetition repairs."""

import json
import logging
import re
import time
from dataclasses import dataclass, field

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
    moves: list[str] = field(default_factory=list)
    guard_violations: list[str] = field(default_factory=list)


def _parse_response(raw: str) -> tuple[str, dict, list[str]]:
    def valid(text: str) -> tuple[str, dict, list[str]] | None:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("reply"), str):
            return None
        action = parsed.get("action")
        moves = parsed.get("moves")
        allowed = {"reflect", "affirm", "give", "summarize", "ask"}
        moves = [move for move in moves if isinstance(move, str) and move in allowed] if isinstance(moves, list) else []
        return parsed["reply"], action if isinstance(action, dict) else {"type": "none"}, moves

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
        return config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}, []
    if stripped.startswith('"'):
        try:
            decoded, end = json.JSONDecoder().raw_decode(stripped)
            if isinstance(decoded, str) and not stripped[end:].strip().strip(","):
                return decoded, {"type": "none"}, []
        except ValueError:
            pass
        return config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}, []
    # A truncated JSON string can leave an escaped closing quote and comma
    # after otherwise readable prose. Remove only that transport fragment.
    return re.sub(r'\\"\s*,?\s*$', "", stripped), {"type": "none"}, []


async def run_deep_turn(db, turn: CounselorTurnInput, *,
                        roadmap_id: str | None = None,
                        history: list[dict] | None = None,
                        instructions: str | None = None,
                        safety_level: str | None = None) -> DeepTurnResult:
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
    prompt = load_prompt("voice") + "\n\n" + context.text
    if instructions:
        prompt += "\n\n" + load_prompt(instructions)
        if instructions == "wellbeing":
            prompt += "\n<safety_level>" + str(safety_level or "concern") + "</safety_level>"
            if safety_level == "urgent":
                prompt += "\n<wellbeing_resources>" + config.PAI_WELLBEING_RESOURCES + "</wellbeing_resources>"
    model_ms = 0
    polish_ms = 0
    language_retried = False
    async def generate(system_prompt, phase):
        nonlocal model_ms, polish_ms, language_retried
        for attempt in range(2):
            started = time.monotonic()
            raw = await chat_completion(role="counselor",
                api_key=config.PAI_API_KEY, model=resolve_model("counselor"),
                messages=messages,
                system_prompt=system_prompt + ("\n\n" + load_prompt("language_retry") if attempt else ""),
                response_format={"type": "json_object"},
                reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
                base_url=config.PAI_BASE_URL,
                phase="counselor_retry" if attempt else phase, turn_id=turn.source_event_id)
            model_ms += int((time.monotonic() - started) * 1000)
            started = time.monotonic()
            reply, action, moves = _parse_response(raw)
            reply = polish_reply(reply)
            blocked = contains_blocked_script(reply, config.PAI_LANGUAGE_BLOCKED_SCRIPTS)
            polish_ms += int((time.monotonic() - started) * 1000)
            if not blocked:
                return (reply, action, moves) if reply else (config.PAI_COUNSELOR_FALLBACK_REPLY, {"type":"none"}, [])
            if language_retried:
                break
            language_retried = True
        return config.PAI_COUNSELOR_FALLBACK_REPLY, {"type":"none"}, []

    reply, action, moves = await generate(prompt, "counselor")
    violations = []
    if instructions != "wellbeing" and action.get("type") != "wellbeing":
        from app.pai_c.voice.guards import repeated_questions, remove_repeated
        avoid = context.plan.avoid_questions if context.plan is not None else []
        started = time.monotonic()
        repeated = repeated_questions(reply, history, avoid)
        polish_ms += int((time.monotonic() - started) * 1000)
        if repeated:
            violations.append("repeated_question")
            line = ("Your draft repeated a question already asked: " + repeated[0][2]
                    + ". Do not ask it again. Reflect what you know or ask about something new.")
            reply, action, moves = await generate(prompt + "\n\n" + line, "counselor_repeat_retry")
            started = time.monotonic()
            if action.get("type") != "wellbeing":
                repeated = repeated_questions(reply, history, avoid)
                cleaned = remove_repeated(reply, repeated)
                if repeated and cleaned:
                    reply = cleaned
                    violations.append("repeat_removed")
            polish_ms += int((time.monotonic() - started) * 1000)
    return DeepTurnResult(reply, action, context, model_ms, polish_ms, moves, violations)
