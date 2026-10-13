"""Offline gateway contracts and backend architecture boundaries."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.config import config
from app.inference import gateway
from app.memory.embeddings import OpenAIEmbeddingProvider


MODELS = {
    'counselor': 'PAI_COUNSELOR_MODEL', 'analyst': 'PAI_ANALYST_MODEL',
    'mirror': 'PAI_MIRROR_MODEL', 'roadmap': 'PAI_ROADMAP_MODEL',
    'sensitive': 'PAI_SENSITIVE_CHECK_MODEL', 'extractor': 'MEMORY_EXTRACTOR_MODEL',
    'document_extractor': 'DOCUMENT_EXTRACTOR_MODEL', 'ocr': 'DOCUMENT_OCR_MODEL',
    'research_extract': 'PAI_MODEL', 'operator': 'PAI_OPERATOR_MODEL',
    'router': 'PAI_MODEL', 'embeddings': 'MEMORY_EMBEDDING_MODEL',
}


@pytest.mark.parametrize('role,setting', MODELS.items())
def test_role_resolves_configured_model(role, setting):
    with patch.object(config, setting, 'configured-model'):
        assert gateway.resolve_model(role) == 'configured-model'


@pytest.mark.parametrize('role,fallback', [
    ('counselor', 'PAI_MODEL'), ('analyst', 'PAI_COUNSELOR_MODEL'),
    ('mirror', 'PAI_COUNSELOR_MODEL'), ('roadmap', 'PAI_COUNSELOR_MODEL'),
    ('sensitive', 'PAI_ANALYST_MODEL'), ('extractor', 'PAI_MODEL'),
    ('document_extractor', 'PAI_MODEL'), ('operator', 'PAI_MODEL'),
])
def test_role_keeps_existing_empty_setting_fallback(role, fallback):
    with patch.object(config, MODELS[role], ''), patch.object(config, fallback, 'fallback-model'):
        assert gateway.resolve_model(role) == 'fallback-model'


def test_ocr_keeps_existing_empty_setting_fallback():
    with patch.object(config, 'DOCUMENT_OCR_MODEL', ''):
        assert gateway.resolve_model('ocr') == 'gpt-5-mini'


@pytest.mark.parametrize('role,setting', [
    ('counselor', 'PAI_COUNSELOR_REASONING_EFFORT'),
    ('mirror', 'PAI_COUNSELOR_REASONING_EFFORT'),
    ('roadmap', 'PAI_COUNSELOR_REASONING_EFFORT'),
    ('analyst', 'PAI_ANALYST_REASONING_EFFORT'),
    ('sensitive', 'PAI_SENSITIVE_CHECK_REASONING_EFFORT'),
    ('document_extractor', 'DOCUMENT_EXTRACTOR_REASONING_EFFORT'),
    ('operator', 'PAI_OPERATOR_REASONING_EFFORT'),
])
def test_role_keeps_reasoning_setting(role, setting):
    with patch.object(config, setting, 'medium'):
        assert gateway.reasoning_effort(role) == 'medium'


@pytest.mark.parametrize('role', ['extractor', 'ocr', 'research_extract', 'router', 'embeddings'])
def test_roles_without_existing_reasoning_setting_omit_it(role):
    assert gateway.reasoning_effort(role) is None


def usage():
    return SimpleNamespace(prompt_tokens=31, completion_tokens=12,
        prompt_tokens_details=SimpleNamespace(cached_tokens=7),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=3))


def fake_client(content='reply'):
    response = SimpleNamespace(usage=usage(), choices=[SimpleNamespace(
        message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=response))), close=AsyncMock())


@pytest.mark.asyncio
async def test_complete_resolves_role_and_preserves_request_and_usage_format(caplog):
    client = fake_client()
    with patch.object(config, 'PAI_COUNSELOR_MODEL', 'gpt-6-sol'), \
         patch.object(config, 'PAI_COUNSELOR_REASONING_EFFORT', 'low'), \
         patch.object(gateway.transport, 'create_client', return_value=client), \
         caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        result = await gateway.complete('counselor', [{'role': 'user', 'content': 'private input'}],
            system_prompt='instructions', response_format={'type': 'json_object'},
            max_tokens=40, temperature=0.2, turn_id='turn-id', api_key='fake-key')
    assert result == 'reply'
    assert client.chat.completions.create.call_args.kwargs == {
        'model': 'gpt-6-sol', 'messages': [{'role': 'system', 'content': 'instructions'},
            {'role': 'user', 'content': 'private input'}], 'reasoning_effort': 'low',
        'max_completion_tokens': 40, 'response_format': {'type': 'json_object'}, 'temperature': 0.2}
    assert caplog.records[-1].getMessage() == (
        'counselor_token_usage phase=counselor turn_id=turn-id model=gpt-6-sol '
        'input=31 cached_input=7 output=12 reasoning=3')
    assert 'private input' not in caplog.text and 'fake-key' not in caplog.text
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_tool_response_keeps_dictionary_even_without_tools(caplog):
    client = fake_client()
    with patch.object(gateway.transport, 'create_client', return_value=client), \
         caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        result = await gateway.complete('operator', [], tools=None, tool_response=True,
                                        api_key='fake', model='gpt-6-sol', turn_id='tool-turn')
    assert result == {'role': 'assistant', 'content': 'reply'}
    assert len([r for r in caplog.records if 'counselor_token_usage' in r.message]) == 1
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_embedding_provider_uses_gateway_and_preserves_vectors_metadata():
    provider = OpenAIEmbeddingProvider('fake-key', 'injected-model', 2, 'https://example.test')
    with patch('app.memory.embeddings.embed', AsyncMock(return_value=[[0.1, 0.2]])) as embed:
        result = await provider.embed_documents(['text'])
    assert result.vectors == [[0.1, 0.2]]
    assert result.model_id == 'openai:injected-model' and result.dimensions == 2
    embed.assert_awaited_once_with('embeddings', ['text'], api_key='fake-key',
                                  model='injected-model', base_url='https://example.test')


@pytest.mark.asyncio
async def test_embed_resolves_model_logs_usage_and_closes_client(caplog):
    response = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])],
                               usage=SimpleNamespace(prompt_tokens=2))
    client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=response)), close=AsyncMock())
    with patch.object(config, 'MEMORY_EMBEDDING_MODEL', 'configured-embedding'), \
         patch.object(gateway.transport, 'create_embedding_client', return_value=client), \
         caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        vectors = await gateway.embed('embeddings', ['text'], api_key='fake', base_url=None,
                                      turn_id='embedding-turn')
    assert vectors == [[0.1, 0.2]]
    client.embeddings.create.assert_awaited_once_with(model='configured-embedding', input=['text'])
    assert 'phase=embeddings turn_id=embedding-turn model=configured-embedding input=2' in caplog.text
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_failure_closes_client():
    client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError('offline failure'))), close=AsyncMock())
    with patch.object(gateway.transport, 'create_embedding_client', return_value=client):
        with pytest.raises(RuntimeError, match='offline failure'):
            await gateway.embed('embeddings', ['text'], api_key='fake', base_url=None)
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ocr_accessor_preserves_raw_response_and_logs_once(caplog):
    client = fake_client('transcription')
    with patch.object(gateway.transport, 'create_client', return_value=client), \
         caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        raw_client = gateway.get_client('ocr', api_key='fake', model='injected-model')
        response = await raw_client.chat.completions.create(model='injected-model', messages=[])
        await raw_client.close()
    assert response.choices[0].message.content == 'transcription'
    client.chat.completions.create.assert_awaited_once_with(model='injected-model', messages=[])
    assert len([r for r in caplog.records if 'phase=ocr ' in r.message]) == 1
    client.close.assert_awaited_once()


def test_sync_classifier_keeps_parameter_shape_and_closes_client(caplog):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(
        return_value=SimpleNamespace(usage=usage(), choices=[SimpleNamespace(message=SimpleNamespace(content=' done '))])))), close=Mock())
    with patch.object(gateway.transport, 'create_sync_client', return_value=client), \
         patch.object(config, 'PAI_MODEL', 'gpt-6-sol'), \
         caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        assert gateway.complete_sync('router', [], api_key='fake', max_tokens=15) == 'done'
    client.chat.completions.create.assert_called_once_with(model='gpt-6-sol', messages=[], max_completion_tokens=15)
    client.close.assert_called_once()
    assert 'phase=router ' in caplog.text


def test_usage_turn_context_preserves_phase_and_restores_previous_turn(caplog):
    with caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        with gateway.token_usage_turn('outer'):
            with gateway.token_usage_turn('inner'):
                gateway.usage_callback('sensitive', 'model')(usage())
            gateway.usage_callback('mirror', 'model')(usage())
    assert 'turn_id=inner' in caplog.records[0].message
    assert 'turn_id=outer' in caplog.records[1].message


def test_no_backend_module_outside_inference_imports_transport_or_provider_sdk():
    root = Path(__file__).resolve().parents[1] / 'app'
    violations = []
    for path in root.rglob('*.py'):
        relative = path.relative_to(root)
        if relative.parts[0] == 'inference':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
                if node.module == 'app.inference':
                    names += ['app.inference.' + item.name for item in node.names]
                if any(item.name == 'AsyncOpenAI' for item in node.names):
                    names.append('openai')
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    names = [node.args[0].value]
                elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                    names = [node.args[0].value]
            if any(isinstance(name, str) and (name == 'openai' or name.startswith('openai.')
                    or name == 'app.inference.client' or name.startswith('app.inference.client.')) for name in names):
                violations.append(f'{relative}:{node.lineno}')
    assert not violations, violations

@pytest.mark.asyncio
async def test_tools_keep_transport_effort_and_tool_call_output():
    client = fake_client()
    message = client.chat.completions.create.return_value.choices[0].message
    message.tool_calls = [SimpleNamespace(id='call-1', function=SimpleNamespace(name='fixture_tool', arguments='{}'))]
    tools = [{'type': 'function', 'function': {'name': 'fixture_tool'}}]
    with patch.object(gateway.transport, 'create_client', return_value=client):
        result = await gateway.complete('operator', [], api_key='fake', model='gpt-6-sol',
                                        reasoning_effort='high', tools=tools)
    assert client.chat.completions.create.call_args.kwargs == {
        'model': 'gpt-6-sol', 'messages': [], 'tools': tools, 'tool_choice': 'auto', 'reasoning_effort': 'none'}
    assert result['tool_calls'] == [{'id': 'call-1', 'type': 'function',
        'function': {'name': 'fixture_tool', 'arguments': '{}'}}]


@pytest.mark.asyncio
async def test_gateway_calls_caller_usage_callback_once(caplog):
    client = fake_client()
    seen = []
    with patch.object(gateway.transport, 'create_client', return_value=client), \
         caplog.at_level(logging.INFO, logger='app.inference.gateway'):
        await gateway.complete('roadmap', [], api_key='fake', usage_callback=seen.append, turn_id='turn')
    assert len(seen) == 1
    assert len([r for r in caplog.records if 'counselor_token_usage' in r.message]) == 1


def test_embedding_transport_preserves_sdk_constructor_defaults():
    with patch.object(gateway.transport, 'AsyncOpenAI') as constructor:
        gateway.transport.create_embedding_client('fake', base_url='https://example.test/custom')
    constructor.assert_called_once_with(api_key='fake', base_url='https://example.test/custom')


@pytest.mark.parametrize('role,prefix', [('extractor', 'MEMORY_EXTRACTOR'),
    ('document_extractor', 'DOCUMENT_EXTRACTOR'), ('ocr', 'DOCUMENT_OCR')])
@pytest.mark.asyncio
async def test_dedicated_credentials_and_endpoint_fallback_are_unchanged(role, prefix):
    with patch.object(config, prefix + '_API_KEY', 'dedicated-key'), \
         patch.object(config, prefix + '_BASE_URL', 'https://example.test/dedicated'), \
         patch.object(gateway.transport, 'chat_completion', AsyncMock(return_value='reply')) as call:
        await gateway.complete(role, [])
    assert call.call_args.kwargs['api_key'] == 'dedicated-key'
    assert call.call_args.kwargs['base_url'] == 'https://example.test/dedicated'
    with patch.object(config, prefix + '_API_KEY', ''), \
         patch.object(config, prefix + '_BASE_URL', ''), \
         patch.object(config, 'PAI_API_KEY', 'fallback-key'), \
         patch.object(config, 'PAI_BASE_URL', 'https://example.test/fallback'), \
         patch.object(gateway.transport, 'chat_completion', AsyncMock(return_value='reply')) as call:
        await gateway.complete(role, [])
    assert call.call_args.kwargs['api_key'] == 'fallback-key'
    assert call.call_args.kwargs['base_url'] == 'https://example.test/fallback'
