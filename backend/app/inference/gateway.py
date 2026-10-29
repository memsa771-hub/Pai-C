"""Single model boundary; transports stay in client.py (OpenAI) and anthropic_client.py.

Existing caller overrides preserve injected provider instances and test seams.
The gateway adds usage records, not new prompts or retries. Each role has a
provider (openai or anthropic) and model from pai_c/policy/model_roles.json,
overridden by PAI_<ROLE>_PROVIDER / PAI_<ROLE>_MODEL; the older model settings
below stay as fallbacks. Every call's estimated cost is recorded for the one
monthly cap (app/inference/usage.py); embeddings also keep their own cap.
"""

import json
import logging
import os
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.config import config
from app.inference import anthropic_client
from app.inference import client as transport
from app.inference.anthropic_client import ProviderUnavailable, UnsupportedForProvider  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)
_turn_id: ContextVar[str] = ContextVar('counselor_token_turn_id', default='')
_DEFAULT = object()
# Each role's own model settings besides PAI_<ROLE>_MODEL (older names still
# work). No role borrows another role's setting; an alias (`same_as` in
# model_roles.json) also reads its target's names.
_MODELS = {
    'classifier': ('PAI_CLASSIFIER_MODEL',),
    'safety': ('PAI_SAFETY_MODEL',),
    'counselor': ('PAI_COUNSELOR_MODEL',),
    'summarizer': ('PAI_SUMMARIZER_MODEL',),
    'analyst': ('PAI_ANALYST_MODEL',),
    'mirror': ('PAI_MIRROR_MODEL',),
    # PAI_ROADMAP_MODEL is the older name for this setting; it still works.
    'path_explain': ('PAI_PATH_EXPLAIN_MODEL', 'PAI_ROADMAP_MODEL'),
    'sensitive': ('PAI_SENSITIVE_CHECK_MODEL',),
    'extractor': ('MEMORY_EXTRACTOR_MODEL',),
    'document_extractor': ('DOCUMENT_EXTRACTOR_MODEL',),
    'ocr': ('DOCUMENT_OCR_MODEL',),
    'researcher': ('PAI_RESEARCHER_MODEL',),
    'operator': ('PAI_OPERATOR_MODEL',),
    'embeddings': ('MEMORY_EMBEDDING_MODEL',),
}
_EFFORTS = {
    'classifier': 'PAI_CLASSIFIER_REASONING_EFFORT',
    'safety': 'PAI_SAFETY_REASONING_EFFORT',
    'counselor': 'PAI_COUNSELOR_REASONING_EFFORT',
    'analyst': 'PAI_ANALYST_REASONING_EFFORT',
    'summarizer': 'PAI_ANALYST_REASONING_EFFORT',
    'mirror': 'PAI_COUNSELOR_REASONING_EFFORT',
    'path_explain': 'PAI_COUNSELOR_REASONING_EFFORT',
    'sensitive': 'PAI_SENSITIVE_CHECK_REASONING_EFFORT',
    'document_extractor': 'DOCUMENT_EXTRACTOR_REASONING_EFFORT',
    'operator': 'PAI_OPERATOR_REASONING_EFFORT',
}


_ROLES_FILE = Path(__file__).resolve().parents[1] / 'pai_c' / 'policy' / 'model_roles.json'
_warned: set = set()


@lru_cache(maxsize=1)
def model_roles() -> dict:
    return json.loads(_ROLES_FILE.read_text(encoding='utf-8'))


@dataclass(frozen=True)
class RoleConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    reasoning_effort: str | None


def _setting(name: str) -> str:
    """A config attribute when one exists, else the raw environment (PAI_<ROLE>_*)."""
    value = getattr(config, name, None)
    return (os.environ.get(name, '') if value is None else value) or ''


def _warn_once(key, message, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def _defaults(role: str) -> dict:
    roles = model_roles()['roles']
    entry = roles.get(role, {'provider': model_roles()['fallback_provider'], 'model': None})
    return roles[entry['same_as']] if 'same_as' in entry else entry


def _fits(provider: str, model: str) -> bool:
    """A model named for another provider (by its prefixes) is never borrowed."""
    def owned_by(name):
        return any(model.lower().startswith(prefix) for prefix in
                   model_roles()['providers'][name].get('model_prefixes', []))
    if model_roles()['providers'][provider].get('model_prefixes'):
        return owned_by(provider)
    return not any(owned_by(name) for name in model_roles()['providers'] if name != provider)


def _provider(role: str) -> str:
    alias = model_roles()['roles'].get(role, {}).get('same_as')
    provider = (_setting(f'PAI_{role.upper()}_PROVIDER') or (alias and _setting(f'PAI_{alias.upper()}_PROVIDER'))
                or _defaults(role)['provider']).strip().lower()
    if provider not in model_roles()['providers']:
        _warn_once(('provider', role, provider), 'model_role_unknown_provider role=%s provider=%s', role, provider)
        provider = model_roles()['fallback_provider']
    key_name = model_roles()['providers'][provider]['api_key']
    if provider != model_roles()['fallback_provider'] and not _setting(key_name):
        # A missing key must not break the stack: run the role on the fallback provider.
        _warn_once(('key', role, provider), 'model_role_provider_unconfigured role=%s provider=%s missing=%s fallback=%s',
                   role, provider, key_name, model_roles()['fallback_provider'])
        provider = model_roles()['fallback_provider']
    return provider


def _model(role: str, provider: str) -> str:
    """The role's own setting, else its data default; PAI_MODEL only for a role
    the data gives no model (operator, router)."""
    alias = model_roles()['roles'].get(role, {}).get('same_as')
    names = dict.fromkeys((f'PAI_{role.upper()}_MODEL', *_MODELS.get(role, ()),
                           *((f'PAI_{alias.upper()}_MODEL', *_MODELS.get(alias, ())) if alias else ())))
    for name in names:
        value = _setting(name).strip()
        if value and _fits(provider, value):
            return value
        if value:
            _warn_once(('model', role, value), 'model_role_model_skipped role=%s provider=%s setting=%s',
                       role, provider, name)
    default = _defaults(role).get('model') or ''
    if default and _fits(provider, default):
        return default
    if not default and config.PAI_MODEL and _fits(provider, config.PAI_MODEL):
        return config.PAI_MODEL
    # The role's default belongs to another provider (the provider was switched by env).
    return model_roles()['providers'][provider].get('default_model') or ''


def resolve_role(role: str) -> RoleConfig:
    provider = _provider(role)
    model = _model(role, provider)
    keys = model_roles()['providers'][provider]
    if provider == model_roles()['fallback_provider']:
        api_key, _, base_url, _ = _settings(role, None, model, _DEFAULT, None)
        return RoleConfig(provider, model, api_key, base_url, reasoning_effort(role))
    return RoleConfig(provider, model, _setting(keys['api_key']), _setting(keys['base_url']) or None, None)


def resolve_model(role: str) -> str:
    return _model(role, _provider(role))


def reasoning_effort(role: str):
    name = _EFFORTS.get(role)
    return (getattr(config, name) or None) if name else None


@contextmanager
def token_usage_turn(turn_id: str):
    token = _turn_id.set(turn_id)
    try:
        yield
    finally:
        _turn_id.reset(token)


def _usage_callback(phase: str, model: str, turn_id: str = '', role: str | None = None) -> Callable[[Any], None]:
    """Log the call's tokens; with a role, also add its estimated cost to the month."""
    def record(usage: Any) -> None:
        if role is not None:
            from app.inference import usage as monthly
            monthly.record_model_call(role, model, usage)
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
    provider = _provider(role)
    if provider != model_roles()['fallback_provider']:
        if tools is not None or tool_response:
            raise UnsupportedForProvider(f'{role} runs on {provider}, which has no tool calls here')
        # Caller overrides name the OpenAI key, endpoint and model; this provider uses its own.
        resolved = resolve_role(role)
        model = model if model and _fits(provider, model) else resolved.model
        settings = model_roles()['providers'][provider]
        if response_format and response_format.get('type') == 'json_object':
            system_prompt = (system_prompt or '') + '\n' + settings['json_instruction']
        record = _usage_callback(phase or role, model, turn_id, role=role)

        def on_provider_usage(usage):
            record(usage)
            if usage_callback is not None:
                usage_callback(usage)
        return await anthropic_client.chat_completion(
            resolved.api_key, model, messages, system_prompt=system_prompt, max_tokens=max_tokens,
            temperature=temperature, base_url=resolved.base_url, settings=settings,
            usage_callback=on_provider_usage)
    api_key, model, base_url, effort = _settings(role, api_key, model, base_url, reasoning_effort)
    if response_format and response_format.get('type') == 'json_object':
        # Chat Completions rejects JSON mode unless a message explicitly asks
        # for JSON. Keep this at the provider boundary for every role.
        system_prompt = (system_prompt or '') + '\nReturn a valid JSON object.'
    record = _usage_callback(phase or role, model, turn_id, role=role)
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
    """Existing transaction-bound classifier: retain synchronous transport (OpenAI only)."""
    _openai_only(role)
    api_key, model, base_url, _ = _settings(role, api_key, model, base_url, None)
    client = transport.create_sync_client(api_key, base_url=base_url)
    try:
        kwargs = {'model': model, 'messages': messages}
        if max_tokens:
            kwargs[transport._token_limit_kwarg(model)] = max_tokens
        response = client.chat.completions.create(**kwargs)
        _usage_callback(phase or role, model, turn_id, role=role)(getattr(response, 'usage', None))
        return response.choices[0].message.content.strip()
    finally:
        client.close()


class _LoggedClient:
    """Raw OCR client seam; record usage without changing raw request/response."""
    def __init__(self, client, role, model, phase, turn_id):
        self._client = client
        async def create(**kwargs):
            response = await client.chat.completions.create(**kwargs)
            _usage_callback(phase or role, kwargs.get('model', model), turn_id, role=role)(
                getattr(response, 'usage', None))
            return response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    def __getattr__(self, name):
        return getattr(self._client, name)


def _openai_only(role: str) -> None:
    provider = _provider(role)
    if provider != model_roles()['fallback_provider']:
        raise UnsupportedForProvider(f'{role} runs on {provider}; this call needs the OpenAI transport')


def get_client(role: str, *, api_key=None, model=None, base_url=_DEFAULT, phase=None, turn_id=''):
    _openai_only(role)
    api_key, model, base_url, _ = _settings(role, api_key, model, base_url, None)
    return _LoggedClient(transport.create_client(api_key, base_url=base_url), role, model, phase, turn_id)


async def embed(role: str, texts: list[str], *, api_key=None, model=None, base_url=_DEFAULT,
                phase=None, turn_id='') -> list[list[float]]:
    if role != 'embeddings':
        raise ValueError('Embedding calls require the embeddings role')
    if not config.PAI_SEMANTIC_RECALL_ENABLED:
        return []
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
    # Monthly cap (app/inference/usage.py): over it, no vectors; callers fall back to lexical.
    from app.inference import usage
    if not usage.embedding_allowed():
        return []
    client = transport.create_embedding_client(api_key, base_url=base_url)
    try:
        response = await client.embeddings.create(model=model, input=texts)
        _usage_callback(phase or role, model, turn_id)(getattr(response, 'usage', None))
        usage.record_embedding(model, texts, getattr(getattr(response, 'usage', None), 'prompt_tokens', None))
        return [item.embedding for item in response.data]
    finally:
        await client.close()


def warm_sdk_imports():
    transport.warm_sdk_imports()
