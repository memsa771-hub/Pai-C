"""Parse Counselor prose and its internal structured state."""

import json
import logging
import re

_RETRY_RESPONSE = "I couldn't finish that reply. Please retry your last message so I can pick up from here."
_DELTA_BUCKETS = ("facts", "records", "memories", "conflicts", "unknowns")
_INTERNAL_OUTPUT = re.compile(
    r"(?i)(counselor[_ ]state|student_understanding_delta|evidence\.quote|"
    r"attribution\.claim_owner|\b(?:fact|record) upsert\b|"
    r"\bcurrent mirror\b|\bnext[_ ]move\b|\bunknowns\s*\(|"
    r'"(?:phase|baseline_ready|final_recommendation)"\s*:|'
    r'\breply (?:with|using) exactly\b)'
)
_SAFE_RESPONSE = "I can help with that. Let's work from what you've shared and take the next useful step."
logger = logging.getLogger(__name__)


def is_counselor_fallback(response: str) -> bool:
    """Exclude failed repair placeholders from future conversational context."""
    return response in {_SAFE_RESPONSE, _RETRY_RESPONSE}


def _student_prose(value: str) -> str:
    """Fail closed if the model puts internal state in the visible reply."""
    text = value.strip()
    return _SAFE_RESPONSE if _INTERNAL_OUTPUT.search(text) else text


async def repair_student_response(raw: str, *, student_message: str,
                                  policy_prompt: str = "") -> str:
    """One bounded rewrite when a model mixes internal state into the answer."""
    from app.config import config
    from app.inference.client import chat_completion
    try:
        rewritten = await chat_completion(
            api_key=config.PAI_API_KEY, model=config.PAI_MODEL,
            messages=[{"role": "user", "content": json.dumps({
                "student_message": student_message, "draft": raw[:5000],
                "turn_policy": policy_prompt[:1200],
            }, ensure_ascii=False)}],
            system_prompt=("Rewrite the draft into one or two short, natural counselor "
                           "paragraphs in the student's language. Help with the student's "
                           "latest request immediately. Use only grounded information in "
                           "the student message and draft. Ask at most one useful question. "
                           "No profile dump, mirror, approval gate, exact reply options, "
                           "schema fields, JSON, status labels, or internal state. "
                           "Return only the student-facing reply."),
            # Reasoning models can spend a 300-token cap before emitting any
            # visible text. Leave enough room for both reasoning and the reply.
            max_tokens=1200, reasoning_effort="low",
            base_url=config.PAI_BASE_URL or None)
        candidate = _student_prose(rewritten)
        if candidate and candidate != _SAFE_RESPONSE:
            return candidate
        logger.warning("counselor response repair returned no usable prose (chars=%d)",
                       len(rewritten))
        return _SAFE_RESPONSE
    except Exception:
        logger.warning("counselor response repair unavailable", exc_info=True)
        return _SAFE_RESPONSE


def needs_response_repair(response: str) -> bool:
    return response == _SAFE_RESPONSE


def parse_turn(raw: str) -> tuple[str, dict]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        # A truncated internal envelope must never be displayed as conversation.
        # Plain prose remains supported for older models and harmless replies.
        if text.startswith(("{", "[")) and any(
                f'"{key}"' in text for key in ("response", "counselor_state", "student_understanding_delta")):
            return _RETRY_RESPONSE, {}
        return _student_prose(raw or "") or _RETRY_RESPONSE, {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
        return _RETRY_RESPONSE, {}
    state = parsed.get("counselor_state")
    if not isinstance(state, dict):
        state = {}
    delta = state.get("student_understanding_delta")
    if not isinstance(delta, dict):
        delta = {}
    state["student_understanding_delta"] = {
        key: [item for item in value[:20] if isinstance(item, dict)]
        if isinstance(value := delta.get(key), list) else []
        for key in _DELTA_BUCKETS
    }
    if not isinstance(state.get("next_move"), dict):
        state["next_move"] = {}
    # Persistence still validates every proposal against the durable owner event;
    # successful parsing conveys no authority to change canonical state.
    return _student_prose(parsed["response"]) or _RETRY_RESPONSE, state
