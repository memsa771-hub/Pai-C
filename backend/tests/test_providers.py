"""Provider per role: resolution from model_roles.json and env, the Anthropic
transport behind complete(), its fallbacks, and the .env name script (offline)."""
import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anthropic
import httpx
import pytest

from app.config import config
from app.inference import gateway, usage
from app.pai_c import opening
from app.pai_c.deep.turn import run_deep_turn
from app.models import User
from scripts import env_add_missing
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn


@pytest.fixture(autouse=True)
def fresh_warnings():
    gateway._warned.clear()
    yield
    gateway._warned.clear()


def test_role_resolution_from_data_and_env():
    with patch.object(config, "ANTHROPIC_API_KEY", "anthropic-key"), \
            patch.object(config, "ANTHROPIC_BASE_URL", ""), \
            patch.object(config, "PAI_COUNSELOR_PROVIDER", ""), \
            patch.object(config, "PAI_COUNSELOR_MODEL", "gpt-5.4-mini"), \
            patch.object(config, "PAI_RESEARCHER_MODEL", ""), \
            patch.object(config, "PAI_ANALYST_MODEL", "claude-sonnet-5-5"), \
            patch.object(config, "PAI_MODEL", "gpt-5.4-mini"), \
            patch.object(config, "PAI_API_KEY", "openai-key"):
        # Data default: counselor on Anthropic; an OpenAI model named by the old setting is not borrowed.
        assert gateway.resolve_role("counselor") == gateway.RoleConfig(
            "anthropic", "claude-sonnet-5-5", "anthropic-key", None, None)
        with patch.object(config, "PAI_COUNSELOR_MODEL", "claude-opus-5"):
            assert gateway.resolve_role("counselor").model == "claude-opus-5"
        with patch.object(config, "PAI_COUNSELOR_PROVIDER", "openai"):
            role = gateway.resolve_role("counselor")
            assert (role.provider, role.model, role.api_key) == ("openai", "gpt-5.4-mini", "openai-key")
        # The new researcher role takes the data default; its aliases follow its setting.
        assert gateway.resolve_role("researcher").model == "gpt-5"
        with patch.object(config, "PAI_RESEARCHER_MODEL", "gpt-6"):
            assert gateway.resolve_role("researcher").model == "gpt-6"
            assert gateway.resolve_role("research_extract").model == "gpt-6"
            assert gateway.resolve_role("path_explain").model == "gpt-6"
        # An OpenAI role never runs a Claude model inherited from another setting.
        analyst = gateway.resolve_role("analyst")
        assert (analyst.provider, analyst.model) == ("openai", "gpt-5.4-mini")
        # PAI_<ROLE>_PROVIDER from the environment switches any role.
        with patch.dict(os.environ, {"PAI_MIRROR_PROVIDER": "anthropic"}), \
                patch.object(config, "PAI_MIRROR_MODEL", "gpt-5"):
            mirror = gateway.resolve_role("mirror")
            assert (mirror.provider, mirror.model, mirror.api_key) == (
                "anthropic", "claude-sonnet-5-5", "anthropic-key")
        assert gateway.resolve_role("extractor").provider == "openai"


def _anthropic(text='{"reply": "Hello."}', error=None):
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=30,
                              cache_creation_input_tokens=0))
    create = AsyncMock(side_effect=error) if error else AsyncMock(return_value=response)
    client = SimpleNamespace(messages=SimpleNamespace(create=create), close=AsyncMock())
    return client


@pytest.mark.asyncio
async def test_anthropic_client_maps_request_and_records_usage(caplog):
    client = _anthropic()
    seen, recorded = [], []
    with patch.object(config, "ANTHROPIC_API_KEY", "anthropic-key"), \
            patch.object(config, "PAI_COUNSELOR_PROVIDER", ""), \
            patch.object(config, "PAI_COUNSELOR_MODEL", ""), \
            patch("app.inference.anthropic_client.AsyncAnthropic", return_value=client) as constructor, \
            patch.object(usage, "record_model_call", side_effect=lambda *args: recorded.append(args)), \
            caplog.at_level(logging.INFO, logger="app.inference.gateway"):
        result = await gateway.complete("counselor", [
                {"role": "system", "content": "Extra rule."}, {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "Hello."}, {"role": "user", "content": "more"}],
            system_prompt="instructions", response_format={"type": "json_object"}, max_tokens=300,
            temperature=0.3, reasoning_effort="low", api_key="openai-key", base_url="https://openai.test",
            usage_callback=seen.append, turn_id="turn-1")
        await gateway.complete("counselor", [], system_prompt="opening")
    assert result == '{"reply": "Hello."}'
    assert constructor.call_args.kwargs["api_key"] == "anthropic-key"
    assert "base_url" not in constructor.call_args.kwargs
    first, second = (call.kwargs for call in client.messages.create.await_args_list)
    assert first == {"model": "claude-sonnet-5-5", "max_tokens": 300, "temperature": 0.3,
        "system": "instructions\n" + gateway.model_roles()["providers"]["anthropic"]["json_instruction"]
                  + "\n\nExtra rule.",
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello."},
                     {"role": "user", "content": "more"}]}
    # A conversation with no turns opens with the data's empty turn; max_tokens has a data default.
    assert second["messages"] == [{"role": "user", "content": "Begin."}] and second["max_tokens"] == 2048
    assert seen[0].prompt_tokens == 130 and seen[0].prompt_tokens_details.cached_tokens == 30
    assert "phase=counselor turn_id=turn-1 model=claude-sonnet-5-5 input=130 cached_input=30 output=20" in caplog.text
    assert [(role, model) for role, model, _ in recorded] == [("counselor", "claude-sonnet-5-5")] * 2
    assert client.close.await_count == 2


@pytest.mark.asyncio
async def test_tools_are_unsupported_for_anthropic():
    with patch.object(config, "ANTHROPIC_API_KEY", "anthropic-key"), \
            patch.object(config, "PAI_COUNSELOR_PROVIDER", "anthropic"), \
            patch("app.inference.anthropic_client.AsyncAnthropic") as constructor:
        with pytest.raises(gateway.UnsupportedForProvider):
            await gateway.complete("counselor", [], tools=[{"type": "function"}])
        with pytest.raises(gateway.UnsupportedForProvider):
            gateway.get_client("counselor")
    constructor.assert_not_called()


def _openai_client(content):
    response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response))),
                           close=AsyncMock())


@pytest.mark.asyncio
async def test_anthropic_failure_falls_back(caplog):
    # 1. No ANTHROPIC_API_KEY: the counselor runs on OpenAI, with one warning.
    openai_client = _openai_client("reply")
    with patch.object(config, "ANTHROPIC_API_KEY", ""), \
            patch.object(config, "PAI_COUNSELOR_PROVIDER", "anthropic"), \
            patch.object(config, "PAI_COUNSELOR_MODEL", "gpt-5.4-mini"), \
            patch.object(gateway.transport, "create_client", return_value=openai_client), \
            caplog.at_level(logging.WARNING, logger="app.inference.gateway"):
        assert gateway.resolve_role("counselor").provider == "openai"
        assert await gateway.complete("counselor", [], api_key="fake") == "reply"
        assert await gateway.complete("counselor", [], api_key="fake") == "reply"
    assert openai_client.chat.completions.create.await_args.kwargs["model"] == "gpt-5.4-mini"
    assert len([r for r in caplog.records if "model_role_provider_unconfigured" in r.getMessage()]) == 1
    assert "ANTHROPIC_API_KEY" in caplog.text

    # 2. The SDK fails: the turn and the opening use their fixed replies.
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://anthropic.test"))
    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "ANTHROPIC_API_KEY", "anthropic-key"), \
            patch.object(config, "PAI_COUNSELOR_PROVIDER", "anthropic"), \
            patch("app.inference.anthropic_client.AsyncAnthropic", return_value=_anthropic(error=error)):
        result = await run_deep_turn(db, _turn(student), history=[])
        assert result.reply == config.PAI_COUNSELOR_FALLBACK_REPLY
        assert "provider_fallback" in result.guard_violations
        db.get(User, student.user_id).display_name = "Alex"
        db.commit()
        job = SimpleNamespace(id="opening-job", workspace_id=student.workspace_id, attempts=3, max_attempts=3)
        assert (await opening.opening_job(job, db))["status"] == "posted"
    assert student.transcript[-1]["content"] == config.PAI_OPENING_FALLBACK_REPLY.replace("{name}", "Alex")


def test_env_script_adds_only_missing_names(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_bytes(b"PAI_API_KEY=very-secret-value\r\nexport PAI_COUNSELOR_MODEL=gpt-x\r\n# ANTHROPIC_API_KEY=old")
    added = env_add_missing.main(["--env", str(env), "ANTHROPIC_API_KEY", "PAI_COUNSELOR_MODEL=claude-sonnet-5-5",
                                  "PAI_COUNSELOR_PROVIDER=anthropic", "PAI_API_KEY"])
    assert added == 0
    text = env.read_bytes().decode("utf-8")
    assert text.startswith("PAI_API_KEY=very-secret-value\r\nexport PAI_COUNSELOR_MODEL=gpt-x\r\n# ANTHROPIC_API_KEY=old\n")
    assert text.endswith("ANTHROPIC_API_KEY=\nPAI_COUNSELOR_PROVIDER=anthropic\n")
    out = capsys.readouterr().out
    assert out.strip() == "added: ANTHROPIC_API_KEY, PAI_COUNSELOR_PROVIDER"
    assert "very-secret" not in out and "gpt-x" not in out
    # Running again adds nothing.
    assert env_add_missing.add_missing(env, ["ANTHROPIC_API_KEY", "PAI_COUNSELOR_PROVIDER=openai"]) == []
    assert env_add_missing.add_missing(env, env_add_missing.BETA_NAMES)[0] == "PAI_RESEARCHER_MODEL"
