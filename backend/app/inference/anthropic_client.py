"""Anthropic Messages transport behind the gateway's `complete()` contract.

The gateway hands over the same arguments it gives the OpenAI transport and
gets plain text back, so callers keep their JSON parse-and-retry. Usage is
reshaped to the OpenAI field names (prompt/completion/cached tokens) so one
usage callback, one cost estimate and the research budget read both providers.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Optional

try:
    from anthropic import AnthropicError, AsyncAnthropic
except ImportError:  # SDK absent: an anthropic role fails at call time, never at import
    AsyncAnthropic = None

    class AnthropicError(Exception):
        pass


class UnsupportedForProvider(ValueError):
    """The request needs something this provider path does not offer (tools)."""


class ProviderUnavailable(RuntimeError):
    """The provider failed; callers with a fixed fallback reply use it."""


def create_client(api_key: str, base_url: Optional[str] = None, timeout: float = 120):
    from app.config import config
    if AsyncAnthropic is None:
        raise ProviderUnavailable("anthropic SDK is not installed")
    kwargs: dict = {"api_key": api_key, "timeout": timeout, "max_retries": config.LLM_MAX_RETRIES}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncAnthropic(**kwargs)


def _messages(messages: list[dict], system_prompt: Optional[str], empty_turn: str) -> tuple[str, list[dict]]:
    """System turns join the system prompt; the conversation must open with a user turn."""
    system = [system_prompt] if system_prompt else []
    turns: list[dict] = []
    for message in messages:
        role, content = message.get("role"), message.get("content") or ""
        if role == "system":
            system.append(str(content))
        elif turns and turns[-1]["role"] == role and isinstance(content, str) and isinstance(turns[-1]["content"], str):
            turns[-1]["content"] += "\n\n" + content
        else:
            turns.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": empty_turn})
    return "\n\n".join(part for part in system if part), turns


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


async def chat_completion(api_key: str, model: str, messages: list[dict], *, system_prompt: Optional[str] = None,
                          max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                          base_url: Optional[str] = None, settings: dict,
                          usage_callback: Optional[Callable[[Any], None]] = None) -> str:
    """`settings` is the provider block of model_roles.json (max tokens, empty turn)."""
    system, turns = _messages(messages, system_prompt, settings["empty_conversation"])
    kwargs: dict = {"model": model, "max_tokens": max_tokens or settings["default_max_tokens"], "messages": turns}
    if system:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    client = create_client(api_key, base_url=base_url)
    try:
        try:
            response = await client.messages.create(**kwargs)
        except AnthropicError as exc:
            raise ProviderUnavailable(type(exc).__name__) from exc
        usage = openai_shaped_usage(getattr(response, "usage", None))
        from app.plugins._shared.budget import record_model_usage
        record_model_usage(usage)
        if usage_callback is not None:
            usage_callback(usage)
        return "".join(getattr(block, "text", "") for block in (response.content or [])
                       if getattr(block, "type", "text") == "text")
    finally:
        await client.close()
