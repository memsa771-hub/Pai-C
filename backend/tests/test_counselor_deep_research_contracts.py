"""Research assertions retained from retired evaluators; no provider calls."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from app.counseling.deep.polish import polish_reply, question_count
from app.counseling.stages import require_counselor_transition
from app.plugins._shared.verification import SourceVerifier, official_url
from app.plugins.gap_assessment import assess, assess_rule
from app.plugins.roadmap_builder import build


def test_deep_research_keeps_reported_evidence_and_requires_cited_rules():
    rule = {"field": "test.score", "source_url": "https://example.edu/entry",
            "checked_at": "2026-10-06", "comparator": "gte", "threshold": 7}
    fact = {"value": 7.5, "evidence_level": "student_reported"}
    assert assess_rule(rule, {"test.score": fact})["student_evidence"] == "student_reported"
    assert assess_rule({**rule, "source_url": ""}, {"test.score": fact})["status"] == "unknown"
    assert assess_rule(rule, {})["status"] == "unknown"
    remedial = {**rule, "remediation": {"action": "Complete a preparatory route",
                                         "source_url": "https://example.edu/preparation"}}
    assert assess_rule(remedial, {"test.score": 6})["status"] == "fixable"
    assert assess_rule({**rule, "field": "education.transcript"}, {})["status"] == "unknown"


def test_deep_research_rethink_and_single_question_contracts():
    assert require_counselor_transition("PROPOSED", "DIRECTION") == "DIRECTION"
    assert question_count(polish_reply("One? Two?")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [None, 7])
@pytest.mark.parametrize("family", [None, "A different study route"])
async def test_deep_recorded_routes_preserve_sources_alternatives_and_missing_fact_request(score, family):
    # The old ten-persona evaluator repeated these same contracts with different
    # labels. Cover each distinct score/family combination directly instead.
    observed = datetime.now(timezone.utc) - timedelta(minutes=2)
    corroborated = observed + timedelta(minutes=1)
    claim = {"kind": "requirement", "field": "test.score", "value": 7,
             "quote": "Test score 7", "comparator": "gte", "threshold": 7,
             "unit": "points", "checked_at": observed.isoformat()}

    def verified_at(url):
        sourced = {**claim, "source_url": url}
        return SourceVerifier().verify(
            claims=[sourced], source_url=url, official_domains={"example.edu"},
            intake="winter 2027", page_text="Winter 2027: Test score 7 is required.",
            checked_at=observed,
            corroboration=[{**sourced, "source_url": "https://example.edu/admissions",
                            "checked_at": corroborated.isoformat()}],
            corroborated_at=corroborated)

    assert verified_at("https://example.edu/entry").status == "verified"
    assert not official_url("https://example.edu.evil.test/entry", {"example.edu"})

    async def child(capability_id, payload):
        if capability_id == "program.discover":
            slug = quote(str(payload["objective"]), safe="")
            return {"candidates": [{"title": payload["objective"],
                                    "url": f"https://example.edu/{slug}"}], "unconfirmed": []}
        if capability_id == "program.research":
            url = payload["url"]
            return {"requirements": [{"country": payload["country"], "status": verified_at(url).status,
                    "source_url": url, "checked_at": observed.isoformat(),
                    "requirement_set_id": url, "rules": [{**claim, "source_url": url}]}],
                    "unconfirmed": []}
        if capability_id == "qualification.recognize":
            return {"procedures": [], "recognition": "unknown", "unconfirmed": []}
        if capability_id == "scholarship.discover":
            return {"scholarships": [], "unconfirmed": []}
        if capability_id == "gap.assess":
            return await assess(None, payload)
        raise AssertionError(f"Unexpected capability: {capability_id}")

    domains = {"tests": {"facts": {"test.score": score}}} if score is not None else {}
    output = await build(SimpleNamespace(capabilities=child, student_context={"domains": domains}), {
        "brief": {"stated_preference": "Further study", "underlying_objective": "Career development",
                  "country": "Example destination", "level": "bachelor", "intake": "winter 2027",
                  "family_wish": {"suggested_direction": family} if family else None}})
    routes = output["roadmaps"]
    origins = {row["origin"] for row in routes}
    assert {"stated_goal", "alternative"} <= origins
    assert ("family_wish" in origins) == bool(family)
    assert all(row["sources"] and all(official_url(source["url"], {"example.edu"})
               for source in row["sources"]) for row in routes)
    requests = (output.get("pending_action") or {}).get("items") or []
    assert len(requests) == (1 if score is None else 0)
    assert all(row["fit_level"] == ("partial" if score is None else "strong") for row in routes)
