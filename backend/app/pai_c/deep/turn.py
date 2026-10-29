"""One fast Counselor model call, with bounded language and repetition repairs."""

import json
import logging
import re
import time
from pathlib import Path
from dataclasses import dataclass, field

from app.config import config
from app.pai_c.deep.context import DeepContext, build_context
from app.pai_c.deep.polish import contains_blocked_script, polish_reply
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.pai_c.memory import MemoryService
from app.inference import usage
from app.inference.gateway import ProviderUnavailable, complete as chat_completion, resolve_model

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


def unfence(raw: str) -> str:
    """Drop a Markdown code fence some models put around JSON."""
    return re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.IGNORECASE).strip()


def _parse_response(raw: str, *, violations=None) -> tuple[str, dict, list[str]]:
    def valid(text: str) -> tuple[str, dict, list[str]] | None:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("reply"), str):
            return None
        action = parsed.get("action")
        moves = parsed.get("moves")
        allowed = {"reflect", "give", "summarize", "ask"}
        moves = [move for move in moves if isinstance(move, str) and move in allowed] if isinstance(moves, list) else []
        return parsed["reply"], action if isinstance(action, dict) else {"type": "none"}, moves

    first = valid(raw)
    if first is not None:
        return first
    second = valid(unfence(raw))
    if second is not None:
        return second
    if violations is not None and "invalid_json_fallback" not in violations:
        violations.append("invalid_json_fallback")
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


async def _append_next_step(db, turn, decision, reply, action):
    """The phase's next step (next_steps.json), in the student's language, after the reply."""
    from app.pai_c.language import render_copy
    step = decision.next_step or {}
    if not step.get("text"):
        return reply, action
    line = await render_copy(db, turn.workspace_id, step["key"], step["text"])
    reply = polish_reply((reply.rstrip() + " " + line).strip())
    if step.get("place") and action.get("type", "none") == "none":
        action = {"type": "show_place", "place": step["place"]}
    return reply, action


async def run_deep_turn(db, turn: CounselorTurnInput, *,
                        history: list[dict] | None = None,
                        instructions: str | None = None,
                        safety_level: str | None = None,
                        decision=None, signals=None) -> DeepTurnResult:
    context = await build_context(db, turn.workspace_id, turn, wellbeing=instructions == "wellbeing", decision=decision, signals=signals)
    if decision is not None and decision.action == "clear_myth" and instructions != "wellbeing":
        from app.pai_c.myths import reply
        return DeepTurnResult(reply(db, turn.workspace_id, decision.topic), {"type": "none"}, context, 0, 0)
    owner_id = turn.source.removeprefix("human:") if turn.source.startswith("human:") else ""
    if history is None:
        history = [{"role": item["role"], "content": item["content"]}
                   for item in MemoryService(db).recent_turns(turn, owner_id,
                                              limit=config.PAI_COUNSELOR_HISTORY_SIZE)]
    current = turn.student_text.strip() or "I attached a document."
    messages = [*history, {"role": "user", "content": current}]
    # Read transactions must not remain open over the network call.
    db.rollback()
    voice_prompt = "voice_guided" if decision is not None else "voice"
    prompt = load_prompt(voice_prompt) + "\n\n" + context.text
    if instructions:
        prompt += "\n\n" + load_prompt(instructions)
        if instructions == "wellbeing":
            prompt += "\n<safety_level>" + str(safety_level or "concern") + "</safety_level>"
            if safety_level == "urgent":
                prompt += "\n<wellbeing_resources>" + config.PAI_WELLBEING_RESOURCES + "</wellbeing_resources>"
    model_ms = 0
    polish_ms = 0
    violations = []
    retry_line = ""
    if instructions != "wellbeing" and not usage.role_allowed("counselor"):
        # Monthly cap reached: a fixed reply that says PAI is paused, no model call.
        return DeepTurnResult(config.PAI_COUNSELOR_FALLBACK_REPLY + "\n\n" + usage.paused_line(),
                              {"type": "none"}, context, 0, 0, [], ["cap_paused"])
    from app.pai_c.voice.guards import drives, repeated_questions, remove_repeated, question_sentences, repeats_previous_reply
    for attempt in range(2):
        started = time.monotonic()
        try:
            raw = await chat_completion(role="counselor",
                api_key=config.PAI_API_KEY, model=resolve_model("counselor"), messages=messages,
                system_prompt=prompt + ("\n\n" + retry_line if retry_line else ""),
                response_format={"type": "json_object"},
                reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
                base_url=config.PAI_BASE_URL,
                phase="counselor_retry" if attempt else "counselor", turn_id=turn.source_event_id)
        except ProviderUnavailable as exc:
            # Wellbeing keeps its own fallback (runtime); any other turn gets the fixed reply.
            if instructions == "wellbeing":
                raise
            logger.warning("counselor_provider_unavailable turn_id=%s error=%s", turn.source_event_id, exc)
            violations.append("provider_fallback")
            return DeepTurnResult(config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}, context,
                                  model_ms, polish_ms, [], violations)
        model_ms += int((time.monotonic() - started) * 1000)
        started = time.monotonic()
        reply, action, moves = _parse_response(raw, violations=violations)
        if instructions == "wellbeing" or action.get("type") == "wellbeing":
            break
        if contains_blocked_script(reply, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            if attempt == 0:
                retry_line = load_prompt("language_retry")
                polish_ms += int((time.monotonic() - started) * 1000)
                continue
            reply, action, moves = config.PAI_COUNSELOR_FALLBACK_REPLY, {"type": "none"}, []
            violations.append("language_fallback")
        if decision is not None and not decision.question_allowed:
            questions = list(question_sentences(reply))
            if questions:
                cleaned = remove_repeated(reply, questions)
                if cleaned:
                    reply = cleaned
                    violations.append("question_removed")
                elif attempt == 0:
                    violations.append("question_retry")
                    retry_line = (Path(__file__).parent.parent / "policy/prompts/question_retry.md").read_text(encoding="utf-8").strip()
                    polish_ms += int((time.monotonic() - started) * 1000)
                    continue
                else:
                    reply = config.PAI_STATEMENT_FALLBACK_REPLY
                    violations.append("statement_fallback")
        from app.pai_c.fact_cards import validated_card
        card = validated_card(action, context.fact_cards, turn.student_text) if decision is not None and decision.question_allowed else None
        if card is not None and list(question_sentences(reply)):
            reply = remove_repeated(reply, list(question_sentences(reply))) or config.PAI_STATEMENT_FALLBACK_REPLY
            violations.append("card_question_removed")
        from app.pai_c.deep.grounding import allowed_context, guard_reply
        reply, grounding_violations = guard_reply(reply, raw, context.world_facts,
                                                  allowed_context(context.text) + turn.student_text)
        violations.extend(grounding_violations)
        reply = polish_reply(reply)
        avoid = context.plan.avoid_questions if context.plan is not None else []
        repeated = repeated_questions(reply, history, avoid)
        if repeated:
            if "repeated_question" not in violations:
                violations.append("repeated_question")
            if attempt == 0:
                retry_line = ("Your draft repeated a question already asked: " + repeated[0][2]
                    + ". Do not ask it again. Reflect what you know or ask about something new.")
                polish_ms += int((time.monotonic() - started) * 1000)
                continue
            cleaned = remove_repeated(reply, repeated)
            if cleaned:
                reply = cleaned
                violations.append("repeat_removed")
        if not repeated and repeats_previous_reply(reply, history):
            if "repeated_reply" not in violations:
                violations.append("repeated_reply")
            if attempt == 0:
                retry_line = (Path(__file__).parent.parent / "policy/prompts/reply_retry.md").read_text(encoding="utf-8").strip()
                polish_ms += int((time.monotonic() - started) * 1000)
                continue
        # The drive rule: the reply ends with the next step (a question or a
        # concrete action); one rewrite, then the step is appended (data copy).
        if decision is not None and decision.must_drive and card is None and not drives(reply, decision.next_step):
            if attempt == 0:
                violations.append("drive_retry")
                retry_line = (Path(__file__).parent.parent / "policy/prompts/drive_retry.md").read_text(
                    encoding="utf-8").strip().replace("{next_step}", (decision.next_step or {}).get("text", ""))
                polish_ms += int((time.monotonic() - started) * 1000)
                continue
            reply, action = await _append_next_step(db, turn, decision, reply, action)
            violations.append("drive_appended")
        polish_ms += int((time.monotonic() - started) * 1000)
        break
    return DeepTurnResult(reply, action, context, model_ms, polish_ms, moves, violations)
