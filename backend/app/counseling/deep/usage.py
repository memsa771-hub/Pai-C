"""Per-call Counselor token counts without prompt or student content."""

import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)
_turn_id: ContextVar[str] = ContextVar("counselor_token_turn_id", default="")


@contextmanager
def token_usage_turn(turn_id: str):
    token = _turn_id.set(turn_id)
    try:
        yield
    finally:
        _turn_id.reset(token)


def usage_callback(phase: str, model: str, turn_id: str = "") -> Callable[[Any], None]:
    def record(usage: Any) -> None:
        input_details = getattr(usage, "prompt_tokens_details", None)
        output_details = getattr(usage, "completion_tokens_details", None)
        logger.info(
            "counselor_token_usage phase=%s turn_id=%s model=%s input=%d cached_input=%d output=%d reasoning=%d",
            phase, turn_id or _turn_id.get(), model,
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(input_details, "cached_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
            int(getattr(output_details, "reasoning_tokens", 0) or 0),
        )

    return record
