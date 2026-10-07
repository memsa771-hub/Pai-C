import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.plugins.scholarship_discovery import discover


@pytest.mark.asyncio
async def test_official_page_yields_only_exact_unconfirmed_scholarship_facts():
    page = "Merit Scholarship. International applicants may apply. Award GBP 1000."

    async def invoke(name, args):
        if name == "web.search":
            return {"ok": True, "results": [{"title": "Merit Scholarship",
                                               "url": "https://example.edu/scholarship"}]}
        if name == "web.institution_registry":
            return {"ok": True, "data": {"identity": {"domains": ["example.edu"]}}}
        if name == "web.fetch":
            return {"ok": True, "data": {"url": args["url"], "content": page}}
        raise AssertionError(name)

    facts = [{"field": "scholarship.eligibility", "value": "International applicants",
              "quote": "International applicants may apply"},
             {"field": "scholarship.amount", "value": "GBP 1000",
              "quote": "Award GBP 1000"},
             {"field": "scholarship.deadline", "value": "2027-01-01",
              "quote": "Deadline: 2027-01-01"}]
    with patch("app.inference.client.chat_completion",
               AsyncMock(return_value=json.dumps({"facts": facts}))):
        result = await discover(SimpleNamespace(tools=SimpleNamespace(invoke=invoke)),
                                {"country": "UK", "level": "bachelor", "field": "CS"})
    assert len(result["scholarships"]) == 1
    scholarship = result["scholarships"][0]
    assert scholarship["status"] == "unconfirmed"
    assert scholarship["eligibility"]["quote"] == "International applicants may apply"
    assert scholarship["amount"]["quote"] == "Award GBP 1000"
    assert scholarship["deadline"] is None


@pytest.mark.asyncio
async def test_aggregator_search_hit_is_not_used_as_scholarship_fact():
    async def invoke(name, args):
        if name == "web.search":
            return {"ok": True, "results": [{"title": "Scholarship",
                                               "url": "https://agent.example/scholarship"}]}
        if name == "web.institution_registry":
            return {"ok": True, "data": {"identity": None}}
        raise AssertionError(name)
    result = await discover(SimpleNamespace(tools=SimpleNamespace(invoke=invoke)),
                            {"country": "Germany"})
    assert result["scholarships"] == []
    assert result["unconfirmed"][0]["reason"] == "Scholarship page is not on a trusted official domain"
