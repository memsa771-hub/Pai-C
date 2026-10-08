import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.eval import counselor_smoke


def _response(content, prompt=2000, cached=1500, completion=40):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=cached)))


@pytest.mark.asyncio
async def test_smoke_runs_offline_and_stops_at_budget(tmp_path):
    fixture = tmp_path / "m.json"
    fixture.write_text(json.dumps({"profile": {}, "messages": ["a", "b", "c"]}))
    create = AsyncMock(return_value=_response(json.dumps(
        {"reply": "One? Two?", "action": {"type": "none"}})))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    args = SimpleNamespace(model="gpt-5-mini", messages=str(fixture), max_cost_usd=0.0000001,
                           reasoning_effort="low", history_size=20)
    with patch.object(counselor_smoke, "create_client", return_value=client):
        result = await counselor_smoke.run(args)
    assert result["summary"]["turns"] == 1
    assert result["summary"]["multi_question_replies"] == 1
    assert result["turns"][0]["reply"].count("?") == 1
    system = create.await_args.kwargs["messages"][0]["content"]
    assert "<language_policy>" in system and create.await_args.kwargs["response_format"]


def test_smoke_refuses_models_without_a_price(tmp_path):
    args = SimpleNamespace(model="unknown-model", messages="x", max_cost_usd=1,
                           reasoning_effort="low", history_size=20)
    with pytest.raises(SystemExit):
        import asyncio
        asyncio.run(counselor_smoke.run(args))
