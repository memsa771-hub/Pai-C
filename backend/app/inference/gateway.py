"""Single model boundary; transport and provider adaptation remain in client.py.

Existing caller overrides preserve injected provider instances and test seams.
The gateway adds usage records, not new prompts, retries or budget policy.
"""

import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from app.config import config
from app.inference import client as transport

logger = logging.getLogger(__name__)
_turn_id: ContextVar[str] = ContextVar('counselor_token_turn_id', default='')
_DEFAULT = object()
_MODELS = {
    'counselor': ('PAI_COUNSELOR_MODEL', 'PAI_MODEL'),
    'summarizer': ('PAI_SUMMARIZER_MODEL', 'PAI_ANALYST_MODEL', 'PAI_COUNSELOR_MODEL', 'PAI_MODEL'),
    'analyst': ('PAI_ANALYST_MODEL', 'PAI_COUNSELOR_MODEL', 'PAI_MODEL'),
    'mirror': ('PAI_MIRROR_MODEL', 'PAI_COUNSELOR_MODEL', 'PAI_MODEL'),
    'roadmap': ('PAI_ROADMAP_MODEL', 'PAI_COUNSELOR_MODEL', 'PAI_MODEL'),
    'sensitive': ('PAI_SENSITIVE_CHECK_MODEL', 'PAI_ANALYST_MODEL', 'PAI_COUNSELOR_MODEL', 'PAI_MODEL'),
    'extractor': ('MEMORY_EXTRACTOR_MODEL', 'PAI_MODEL'),
    'document_extractor': ('DOCUMENT_EXTRACTOR_MODEL', 'PAI_MODEL'),
    'ocr': ('DOCUMENT_OCR_MODEL',),
    'research_extract': ('PAI_MODEL',),
    'operator': ('PAI_OPERATOR_MODEL', 'PAI_MODEL'),
    'router': ('PAI_MODEL',),
    'embeddings': ('MEMORY_EMBEDDING_MODEL',),
}
_EFFORTS = {
    'counselor': 'PAI_COUNSELOR_REASONING_EFFORT',
    'analyst': 'PAI_ANALYST_REASONING_EFFORT',
    'summarizer': 'PAI_ANALYST_REASONING_EFFORT',
    'mirror': 'PAI_COUNSELOR_REASONING_EFFORT',
    'roadmap': 'PAI_COUNSELOR_REASONING_EFFORT',
    'sensitive': 'PAI_SENSITIVE_CHECK_REASONING_EFFORT',
    'document_extractor': 'DOCUMENT_EXTRACTOR_REASONING_EFFORT',
    'operator': 'PAI_OPERATOR_REASONING_EFFORT',
}


def resolve_model(role: str) -> str:
    for name in _MODELS[role]:
        value = getattr(config, name, '')
        if value:
            return value
    # Existing OCR fallback, not a new model selection policy.
    return 'gpt-5-mini' if role == 'ocr' else ''


def reasoning_effort(role: str):
    resolve_model(role)
    name = _EFFORTS.get(role)
    return (getattr(config, name) or None) if name else None


@contextmanager
def token_usage_turn(turn_id: str):
    token = _turn_id.set(turn_id)
    try:
        yield
    finally:
        _turn_id.reset(token)


def _usage_callback(phase: str, model: str, turn_id: str = '') -> Callable[[Any], None]:
    def record(usage: Any) -> None:
        input_details = getattr(usage, 'prompt_tokens_details', None)
        output_details = getattr(usage, 'completion_tokens_details', None)
        logger.info(
            'counselor_token_usage phase=%s turn_id=%s model=%s input=%d cached_input=%d output=%d reasoning=%d',
            phase, turn_id or _turn_id.get(), model,
            int(getattr(usage, 'prompt_tokens', 0) or 0),
            int(getattr(input_details, 'cached_tokens', 0) or 0),
            int(getattr(usage, 'completion_tokens', 0) or 0),
            int(getattr(output_details, 'reasoning_tokens', 0) or 0),
        )
    return record


# Compatibility name retained for existing instrumentation and offline harnesses.
usage_callback = _usage_callback


def _settings(role, api_key, model, base_url, effort):
    resolved = resolve_model(role)
    prefix = {'extractor': 'MEMORY_EXTRACTOR', 'document_extractor': 'DOCUMENT_EXTRACTOR',
              'ocr': 'DOCUMENT_OCR'}.get(role)
    if api_key is None:
        api_key = (getattr(config, prefix + '_API_KEY', '') if prefix else '') or config.PAI_API_KEY
    if base_url is _DEFAULT:
        base_url = (getattr(config, prefix + '_BASE_URL', '') if prefix else '') or config.PAI_BASE_URL or None
    if effort is _DEFAULT:
        effort = reasoning_effort(role)
    return api_key, model if model is not None else resolved, base_url, effort


async def complete(role: str, messages: list[dict], system_prompt=None, response_format=None,
                   tools=None, *, api_key=None, model=None, base_url=_DEFAULT,
                   reasoning_effort=_DEFAULT, max_tokens=None, temperature=None,
                   phase=None, turn_id='', usage_callback=None, tool_response=False):
    api_key, model, base_url, effort = _settings(role, api_key, model, base_url, reasoning_effort)
    record = _usage_callback(phase or role, model, turn_id)
    def on_usage(usage):
        record(usage)
        if usage_callback is not None:
            usage_callback(usage)
    kwargs = dict(api_key=api_key, model=model, messages=messages, system_prompt=system_prompt,
                  max_tokens=max_tokens, reasoning_effort=effort, base_url=base_url,
                  usage_callback=on_usage)
    if tools is not None or tool_response:
        return await transport.chat_completion_tools(**kwargs, tools=tools)
    return await transport.chat_completion(**kwargs, response_format=response_format, temperature=temperature)


def complete_sync(role: str, messages: list[dict], *, api_key=None, model=None,
                  base_url=_DEFAULT, max_tokens=None, phase=None, turn_id='') -> str:
    """Existing transaction-bound classifier: retain synchronous transport."""
    api_key, model, base_url, _ = _settings(role, api_key, model, base_url, None)
    client = transport.create_sync_client(api_key, base_url=base_url)
    try:
        kwargs = {'model': model, 'messages': messages}
        if max_tokens:
            kwargs[transport._token_limit_kwarg(model)] = max_tokens
        response = client.chat.completions.create(**kwargs)
        _usage_callback(phase or role, model, turn_id)(getattr(response, 'usage', None))
        return response.choices[0].message.content.strip()
    finally:
        client.close()


class _LoggedClient:
    """Raw OCR client seam; record usage without changing raw request/response."""
    def __init__(self, client, role, model, phase, turn_id):
        self._client = client
        async def create(**kwargs):
            response = await client.chat.completions.create(**kwargs)
            _usage_callback(phase or role, kwargs.get('model', model), turn_id)(getattr(response, 'usage', None))
            return response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    def __getattr__(self, name):
        return getattr(self._client, name)


def get_client(role: str, *, api_key=None, model=None, base_url=_DEFAULT, phase=None, turn_id=''):
    api_key, model, base_url, _ = _settings(role, api_key, model, base_url, None)
    return _LoggedClient(transport.create_client(api_key, base_url=base_url), role, model, phase, turn_id)


async def embed(role: str, texts: list[str], *, api_key=None, model=None, base_url=_DEFAULT,
                phase=None, turn_id='') -> list[list[float]]:
    if role != 'embeddings':
        raise ValueError('Embedding calls require the embeddings role')
    model = resolve_model(role) if model is None else model
    # Credential compatibility/Null fallback remains with the existing provider.
    if api_key is None or base_url is _DEFAULT:
        from app.memory.embeddings import resolve_config
        _, resolved_key, _, resolved_url, _ = resolve_config()
        if api_key is None:
            api_key = resolved_key
        if base_url is _DEFAULT:
            base_url = resolved_url or None
    if not texts:
        return []
    client = transport.create_embedding_client(api_key, base_url=base_url)
    try:
        response = await client.embeddings.create(model=model, input=texts)
        _usage_callback(phase or role, model, turn_id)(getattr(response, 'usage', None))
        return [item.embedding for item in response.data]
    finally:
        await client.close()


def warm_sdk_imports():
    transport.warm_sdk_imports()
