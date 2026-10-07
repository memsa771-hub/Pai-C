"""Search resilience and run budgets never require external credentials."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.plugins._shared.budget import bounded_research, record_model_usage, spend
from app.tools.builtin.web import search


@pytest.mark.asyncio
async def test_search_retries_provider_429_then_caches_result():
    request = httpx.Request("GET", "https://search.test")
    response = httpx.Response(429, request=request, headers={"Retry-After": "0"})
    provider = SimpleNamespace(search=AsyncMock(side_effect=[
        httpx.HTTPStatusError("rate limited", request=request, response=response),
        [{"title": "Official page", "url": "https://example.edu"}],
    ]))
    cached = {}

    def store(key, value, ttl):
        assert ttl == 86400
        cached[key] = value

    with patch("app.tools.builtin.web.get_web_search_provider", return_value=provider), \
         patch("app.tools.builtin.web.get_bytes", side_effect=lambda key: cached.get(key)), \
         patch("app.tools.builtin.web.set_bytes", side_effect=store), \
         patch("app.tools.builtin.web.asyncio.sleep", new=AsyncMock()):
        first = await search(None, {"query": "example program", "limit": 5})
        second = await search(None, {"query": "example program", "limit": 5})
    assert first["ok"] and not first["cached"]
    assert second["ok"] and second["cached"]
    assert provider.search.await_count == 2


@pytest.mark.asyncio
async def test_search_has_explicit_unconfigured_and_nonretryable_failure():
    with patch("app.tools.builtin.web.get_web_search_provider", return_value=None):
        result = await search(None, {"query": "program"})
    assert result["error"]["code"] == "search_not_configured"
    request = httpx.Request("GET", "https://search.test")
    response = httpx.Response(400, request=request)
    provider = SimpleNamespace(search=AsyncMock(side_effect=httpx.HTTPStatusError(
        "bad request", request=request, response=response)))
    with patch("app.tools.builtin.web.get_web_search_provider", return_value=provider), \
         patch("app.tools.builtin.web.get_bytes", return_value=None):
        result = await search(None, {"query": "bad"})
    assert not result["ok"] and provider.search.await_count == 1


def test_research_budget_limits_each_tool_and_resets_after_run():
    with bounded_research(queries=1, fetches=2, seconds=60) as budget:
        assert spend("web.search") is None
        assert spend("web.search") == "research_query_budget_exceeded"
        assert spend("web.fetch") is None
        assert spend("web.fetch") is None
        assert spend("web.fetch") == "research_fetch_budget_exceeded"
        record_model_usage(SimpleNamespace(prompt_tokens=120, completion_tokens=30))
        assert budget.usage() == {"queries": 1, "fetches": 2, "model_calls": 1,
                                  "input_tokens": 120, "output_tokens": 30}
    assert spend("web.search") is None
