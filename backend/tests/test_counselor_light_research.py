"""Public cache, private briefs and persistent budgets; offline only."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import config
from app.models import Institution, Opportunity, RequirementSet, Workspace
from app.research.requirements import RequirementStore
from app.counseling.research_gateway import _research_brief
from app.plugins.program_research import research
from app.plugins._shared.budget import bounded_research, spend
from scripts.counselor_eval_support import StudentSession


def seed(db, workspace_id, *, old=False):
    url = "https://official.example/program"
    payload = {"url": url, "country": "fixture", "level": "degree", "intake": "next"}
    db.add(Institution(name="Fixture", normalized_name="fixture", country_code="XX",
        website_url="https://official.example", source="catalog", provider="fixture", provider_id="fixture"))
    opportunity = Opportunity(id=str(uuid4()), workspace_id=workspace_id, institution="Fixture",
        route={"url": url, "private_annotation": "Do not share"}, country="fixture", level="degree", intake="next", url=url)
    checked = datetime.now(timezone.utc) - timedelta(days=400 if old else 0)
    evidence = RequirementSet(id=str(uuid4()), opportunity_id=opportunity.id, source_url=url,
        rules=[{"field": "eligibility", "value": "Completed study", "quote": "Completed study required",
                "source_url": url}], fees={}, deadlines={}, checked_at=checked, version=1, status="verified",
        verification_checks={"public_cache": {"key": RequirementStore.cache_key(url, "fixture", "degree", "next"), "passed": True}})
    db.add_all([opportunity, evidence]); db.commit()
    return payload, evidence


@pytest.mark.asyncio
async def test_cache_hit_skips_all_live_tools_and_model_calls():
    with StudentSession() as student, student.factory() as db:
        payload, evidence = seed(db, student.workspace_id)
        tools = SimpleNamespace(invoke=AsyncMock(side_effect=AssertionError("No live tools")))
        with patch("app.plugins.program_research._extract_page", AsyncMock()) as model:
            result = await research(SimpleNamespace(workspace_id=student.workspace_id, tools=tools), payload)
        assert result["requirements"][0]["cached"]
        assert result["requirements"][0]["rules"][0]["fact_id"].startswith(evidence.id)
        tools.invoke.assert_not_awaited(); model.assert_not_awaited()


def test_public_cache_copy_never_copies_student_route_or_workspace_metadata():
    with StudentSession() as student, student.factory() as db:
        payload, evidence = seed(db, student.workspace_id)
        other = Workspace(name="Other", settings={}); db.add(other); db.commit()
        result = RequirementStore(db).cached(other.id, payload)
        clone = db.get(Opportunity, result["opportunity_id"])
        assert clone.workspace_id == other.id and clone.route == {"url": payload["url"]}
        assert result["requirement_set_id"] != evidence.id
        assert "Do not share" not in str(result)


def test_stale_or_newer_unconfirmed_evidence_is_not_a_cache_hit():
    with StudentSession() as student, student.factory() as db:
        payload, evidence = seed(db, student.workspace_id, old=True)
        assert RequirementStore(db).cached(student.workspace_id, payload) is None
        evidence.checked_at = datetime.now(timezone.utc); evidence.status = "unconfirmed"; db.commit()
        assert RequirementStore(db).cached(student.workspace_id, payload) is None


def test_student_budget_is_persistent_and_stops_before_external_call():
    with StudentSession() as student:
        with patch.object(config, "PAI_RESEARCH_MAX_CALLS_PER_STUDENT", 1):
            with bounded_research(queries=10, fetches=10, seconds=30, workspace_id=student.workspace_id):
                assert spend("web.search") is None
            with bounded_research(queries=10, fetches=10, seconds=30, workspace_id=student.workspace_id):
                assert spend("web.fetch") == "research_student_budget_exceeded"


def test_brief_uses_confirmed_mirror_not_legacy_understanding():
    with StudentSession() as student, student.factory() as db:
        mirror = {"dimensions": [{"key": "stated_goal", "picture": "My original wish"}],
                  "roadmap_lanes": [{"lane": "stated_goal", "why": "Test my wish"}]}
        journey = SimpleNamespace(counselor_summary_draft={"mirror": mirror, "version": 4})
        result = _research_brief(db, student.workspace_id, journey)
        assert result["mirror"] == mirror and result["mirror_version"] == 4
        assert result["stated_preference"] == "My original wish"
        assert "notebook" in result and "profile" in result and "questions" in result
