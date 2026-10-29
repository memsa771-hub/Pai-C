"""Anthropic Messages transport behind the gateway's `complete()` contract.

The gateway hands over the same arguments it gives the OpenAI transport and
gets plain text back, so callers keep their JSON parse-and-retry. Usage is
reshaped to the OpenAI field names (prompt/completion/cached tokens) so one
usage callback, one cost estimate and the research budget read both providers.
"""

import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Optional

try:
    from anthropic import AnthropicError, AsyncAnthropic
except ImportError:  # SDK absent: an anthropic role fails at call time, never at import
    AsyncAnthropic = None

    class AnthropicError(Exception):
        pass

logger = logging.getLogger(__name__)


class UnsupportedForProvider(ValueError):
    """The request needs something this provider path does not offer (tools)."""


class ProviderUnavailable(RuntimeError):
    """The provider failed; callers with a fixed fallback reply use it."""


def create_client(api_key: str, base_url: Optional[str] = None, timeout: float = 120,
                  max_retries: Optional[int] = None):
    from app.config import config
    if AsyncAnthropic is None:
        raise ProviderUnavailable("anthropic SDK is not installed")
    kwargs: dict = {"api_key": api_key, "timeout": timeout,
                    "max_retries": config.LLM_MAX_RETRIES if max_retries is None else max_retries}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncAnthropic(**kwargs)


def _messages(messages: list[dict], system_blocks: list[str], empty_turn: str) -> tuple[list[str], list[dict]]:
    """System turns join the last system block; the conversation must open with a user turn."""
    blocks = [block for block in system_blocks if block]
    extra: list[str] = []
    turns: list[dict] = []
    for message in messages:
        role, content = message.get("role"), message.get("content") or ""
        if role == "system":
            extra.append(str(content))
        elif turns and turns[-1]["role"] == role and isinstance(content, str) and isinstance(turns[-1]["content"], str):
            turns[-1]["content"] += "\n\n" + content
        else:
            turns.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": empty_turn})
    if extra:
        if blocks:
            blocks[-1] = "\n\n".join([blocks[-1], *extra])
        else:
            blocks = ["\n\n".join(extra)]
    return blocks, turns


def openai_shaped_usage(usage: Any) -> SimpleNamespace | None:
    if usage is None:
        return None
    cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return SimpleNamespace(
        prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0) + cached + written,
        completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=written),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )


def _thinking(effort: Optional[str], settings: dict) -> tuple[dict, int]:
    """The reasoning effort as Anthropic thinking: low, none or unset turn it
    off (Sonnet would otherwise think at its own default and bill it as
    output); medium and high get the data's token budget."""
    budget = int(settings.get("thinking_budget_by_effort", {}).get((effort or "").lower(), 0) or 0)
    if budget <= 0:
        return {"type": "disabled"}, 0
    return {"type": "enabled", "budget_tokens": budget}, budget


async def chat_completion(api_key: str, model: str, messages: list[dict], *, system_prompt: Optional[str] = None,
                          system_blocks: Optional[list[str]] = None,
                          max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                          base_url: Optional[str] = None, settings: dict, reasoning_effort: Optional[str] = None,
                          usage_callback: Optional[Callable[[Any], None]] = None) -> str:
    """`settings` is the provider block of model_roles.json with the role's own
    overrides on top (max_tokens, timeout_seconds, max_retries).

    Prompt caching: `system_blocks` (else the one `system_prompt`) are sent as
    separate system blocks and only the first carries the cache breakpoint.
    Anthropic matches a cached prefix only at block boundaries, so the caller
    puts the static prompt first and the per-turn context after it. A reply
    cut off at max_tokens is asked once more for fewer words (on the last,
    uncached block); a second cut-off or a refusal raises ProviderUnavailable,
    so the caller's fixed fallback is used. Any other SDK failure (a bad
    parameter on an older SDK raises TypeError) is also ProviderUnavailable."""
    blocks, turns = _messages(messages, system_blocks if system_blocks else [system_prompt or ""],
                              settings["empty_conversation"])
    thinking, budget = _thinking(reasoning_effort, settings)
    kwargs: dict = {"model": model, "messages": turns, "thinking": thinking,
                    "max_tokens": (max_tokens or settings.get("max_tokens") or settings["default_max_tokens"]) + budget}
    if temperature is not None and not budget:  # thinking accepts no temperature
        kwargs["temperature"] = temperature
    client = create_client(api_key, base_url=base_url, timeout=settings.get("timeout_seconds", 120),
                           max_retries=settings.get("max_retries"))
    try:
        for attempt in range(2):
            texts = list(blocks)
            if attempt:
                texts = texts[:-1] + ["\n\n".join(texts[-1:] + [settings["shorter_instruction"]])]
            if texts:
                kwargs["system"] = [{"type": "text", "text": text, **({"cache_control": {"type": "ephemeral"}}
                                                                    if not index else {})}
                                    for index, text in enumerate(texts)]
            try:
                response = await client.messages.create(**kwargs)
            except AnthropicError as exc:
                raise ProviderUnavailable(type(exc).__name__) from exc
            except (TypeError, ValueError) as exc:  # a parameter this SDK does not take
                logger.warning("anthropic_sdk_error model=%s error_type=%s", model, type(exc).__name__)
                raise ProviderUnavailable(type(exc).__name__) from exc
            usage = openai_shaped_usage(getattr(response, "usage", None))
            from app.plugins._shared.budget import record_model_usage
            record_model_usage(usage)
            if usage_callback is not None:
                usage_callback(usage)
            stop = getattr(response, "stop_reason", None)
            if stop == "refusal":
                logger.warning("anthropic_stop model=%s stop_reason=refusal", model)
                raise ProviderUnavailable("refusal")
            if stop == "max_tokens":
                logger.warning("anthropic_stop model=%s stop_reason=max_tokens attempt=%d", model, attempt + 1)
                continue
            return "".join(getattr(block, "text", "") for block in (response.content or [])
                           if getattr(block, "type", "text") == "text")
        raise ProviderUnavailable("max_tokens")
    finally:
        await client.close()
