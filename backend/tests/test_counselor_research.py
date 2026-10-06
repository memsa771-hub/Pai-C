"""Research provenance, registration, deterministic gaps and review states."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.capabilities import get_capability_registry
from app.plugins.gap_assessment import assess_rule
from app.plugins.qualification_recognition import recognize
from app.plugins.roadmap_builder import build, on_run_status
from app.journey import JourneyService
from app.memory.handlers import resume_research
from app.models import ExecutionRun, MemoryCandidate
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.research.requirements import RequirementStore, ResearchEvidenceError
from app.services import operator
from app.tools import AUDIENCE_OPERATOR, ToolContext
from app.tools.builtin import capabilities as capability_tools
from app.tools.web_search import set_web_search_provider
from app.memory.permissions import OPERATOR_CAPABILITIES
from scripts.counselor_eval_support import StudentSession
from scripts.eval_counselor_journey import check_workflow_scenarios


def test_five_workflow_scenario_invariants():
    assert all(check_workflow_scenarios().values())


def test_six_research_capabilities_register_with_single_owners():
    registry = get_capability_registry()
    expected = {"program.discover", "program.research", "qualification.recognize",
                "scholarship.discover", "gap.assess", "roadmap.build"}
    assert {item.id for item in registry.all()} == expected
    assert registry.owner_for_task_type("roadmap_research").id == "roadmap.build"
    assert registry.get("roadmap.build").uses_capabilities == expected - {"roadmap.build"}


def test_requirement_store_requires_source_and_scopes_review():
    with StudentSession() as student, student.factory() as db:
        store = RequirementStore(db)
        now = datetime.now(timezone.utc)
        with pytest.raises(ResearchEvidenceError, match="source URL"):
            store.propose(student.workspace_id, route={}, country="Germany", source_url="http://example.com",
                          checked_at=now, rules=[])
        with pytest.raises(ResearchEvidenceError, match="Every rule"):
            store.propose(student.workspace_id, route={}, country="Germany", source_url="https://example.edu",
                          checked_at=now, rules=[{"field": "test.score"}])
        opportunity, proposed = store.propose(
            student.workspace_id, route={"program": "CS"}, country="Germany",
            source_url="https://example.edu/cs", checked_at=now,
            rules=[{"field": "test.score", "source_url": "https://example.edu/cs", "value": 7}],
            intake="2027-fall")
        assert store.preferred(student.workspace_id, opportunity.id).id == proposed.id
        assert store.preferred("another-workspace", opportunity.id) is None
        assert store.review(student.workspace_id, proposed.id, reviewer="reviewer", decision="verified").status == "verified"
        _, revision = store.propose(
            student.workspace_id, opportunity_id=opportunity.id,
            route={"program": "CS"}, country="Germany", intake="2027-fall",
            source_url="https://example.edu/cs", checked_at=now, rules=[])
        assert revision.version == 2
        assert store.preferred(student.workspace_id, opportunity.id).id == proposed.id
        with pytest.raises(ResearchEvidenceError, match="Only proposed"):
            store.review(student.workspace_id, proposed.id, reviewer="reviewer", decision="expired")
        db.commit()


def test_gap_assessment_is_deterministic_and_source_bound():
    rule = {"field": "test.score", "source_url": "https://example.edu/entry",
            "checked_at": "2026-10-06T00:00:00+00:00", "comparator": "gte", "threshold": 7}
    assert assess_rule(rule, {})["status"] == "unknown"
    assert assess_rule(rule, {"test.score": 7.5})["status"] == "met"
    assert assess_rule(rule, {"test.score": 6})["status"] == "blocking"
    assert assess_rule({**rule, "source_url": "http://example.edu"}, {"test.score": 8})["status"] == "unknown"
    assert assess_rule(rule, {"test.score": 6}) == assess_rule(rule, {"test.score": 6})


@pytest.mark.asyncio
async def test_country_pack_addition_needs_no_core_change():
    result = await recognize(SimpleNamespace(), {"country": "Germany", "origin_country": "Pakistan"})
    assert result["recognition"] == "unknown"
    assert any("ibcc.edu.pk" in item["source_url"] for item in result["procedures"])
    assert any("daad.de" in item["source_url"] for item in result["procedures"])


@pytest.mark.asyncio
async def test_roadmap_composition_pauses_on_unknown_canonical_field():
    calls = []

    async def child(capability_id, payload):
        calls.append(capability_id)
        if capability_id == "program.discover":
            return {"candidates": [{"url": "https://example.edu/cs", "title": "CS"}],
                    "unconfirmed": []}
        if capability_id == "program.research":
            return {"requirements": [{"country": "Germany", "status": "proposed",
                    "source_url": "https://example.edu/cs", "checked_at": "2026-10-06T00:00:00+00:00",
                    "requirement_set_id": "r1", "rules": [{"field": "test.english_score",
                    "source_url": "https://example.edu/cs", "checked_at": "2026-10-06T00:00:00+00:00",
                    "comparator": "gte", "threshold": 7}]}], "unconfirmed": []}
        if capability_id == "qualification.recognize":
            return {"procedures": [], "recognition": "unknown", "unconfirmed": []}
        if capability_id == "scholarship.discover":
            return {"scholarships": [], "unconfirmed": []}
        if capability_id == "gap.assess":
            from app.plugins.gap_assessment import assess
            return await assess(None, payload)
        raise AssertionError(capability_id)

    context = SimpleNamespace(capabilities=child, student_context={"domains": {"tests": {"facts": {}}}})
    result = await build(context, {"brief": {"stated_preference": "CS in Germany",
                                    "underlying_objective": "international tech career", "country": "Germany"}})
    assert result["pending_action"]["type"] == "need_from_student"
    assert result["pending_action"]["items"][0]["field"] == "test.english_score"
    assert "program.research" in calls and "gap.assess" in calls
    assert result["roadmaps"][0]["research_status"] == "proposed"


def test_research_run_stage_hook_follows_server_transition_graph():
    with StudentSession() as student, student.factory() as db:
        journeys = JourneyService(db)
        journey = journeys.ensure_counselor(student.workspace_id)
        for stage in ("FOUNDATION", "DIRECTION", "RESEARCHING"):
            journey = journeys.set_counselor_stage(student.workspace_id, journey.id, stage)
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                           objective="Research", task_type="roadmap_research", status="verifying",
                           constraints={"research_key": f"{journey.id}:goal"})
        db.add(run)
        db.flush()
        on_run_status(db, run)
        assert journeys.get(student.workspace_id, journey.id).current_stage == "ASSESSING"
        run.status = "needs_user_action"
        run.pending_action = {"type": "need_from_student", "kind": "fact", "items": [{"field": "test.score"}]}
        on_run_status(db, run)
        assert journeys.get(student.workspace_id, journey.id).current_stage == "NEEDS_INFO"
        run.status = "executing"
        on_run_status(db, run)
        run.status = "completed"
        run.result = {"capability_result": {"roadmaps": [{
            "title": "CS", "origin": "stated_goal", "route": {"url": "https://example.edu/cs"},
            "sources": [{"url": "https://example.edu/cs", "checked_at": "2026-10-06T00:00:00+00:00"}],
            "gaps": []}]}}
        on_run_status(db, run)
        assert journeys.get(student.workspace_id, journey.id).current_stage == "PROPOSED"


@pytest.mark.asyncio
async def test_accepted_fact_event_resumes_same_paused_run_without_student_continue():
    with StudentSession() as student, student.factory() as db:
        now = datetime.now(timezone.utc)
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                           objective="Research", task_type="roadmap_research",
                           status="needs_user_action", created_at=now,
                           pending_action={"kind": "fact", "type": "need_from_student",
                                           "items": [{"field": "goal.details.target_countries"}]})
        candidate = MemoryCandidate(workspace_id=student.workspace_id,
                                    candidate_type="student_record", operation="upsert", key="goal",
                                    status="accepted", reconciled_at=now, created_at=now)
        db.add_all((run, candidate))
        db.commit()
        with patch.object(operator, "resume", AsyncMock(return_value={
                "ok": True, "data": {"resumed": True}})) as resumed, \
                patch("app.counseling.research_flow.delegate_research_if_ready",
                      AsyncMock(return_value=None)):
            outcome = await resume_research(SimpleNamespace(
                workspace_id=student.workspace_id, payload={"candidate_id": candidate.id}), db)
        assert outcome["resumed"] == 1
        assert resumed.await_args.args[1] == run.id
        assert resumed.await_args.args[2] == {"candidate_id": candidate.id}


@pytest.mark.asyncio
async def test_fake_official_page_missing_ielts_then_reconciled_score_unblocks_same_brief():
    page = "Applicants need an IELTS overall score of at least 7.0 for this program."
    provider = SimpleNamespace(search=AsyncMock(return_value=[{
        "title": "Computer Science", "url": "https://example.edu/cs"}]))
    api = SimpleNamespace(post=AsyncMock(return_value={"ok": True, "data": {
        "content": page, "url": "https://example.edu/cs"}}))
    claim = '{"facts":[{"field":"test_attempt[IELTS].overall_score","value":7.0,"kind":"requirement",' \
            '"comparator":"gte","threshold":7.0,' \
            '"quote":"Applicants need an IELTS overall score of at least 7.0 for this program."}]}'
    set_web_search_provider(provider)
    try:
        with StudentSession() as student, patch("app.inference.client.chat_completion",
                                               AsyncMock(return_value=claim)):
            ctx = ToolContext(
                workspace_id=student.workspace_id, agent_name="pai-operator", api=api,
                allowed_tools=frozenset({"capability.invoke"}), audience=AUDIENCE_OPERATOR,
                granted_capabilities=OPERATOR_CAPABILITIES,
                required_capability_id="roadmap.build",
            )
            brief = {"stated_preference": "CS in Germany", "underlying_objective": "tech career",
                     "country": "Germany"}
            first = await capability_tools.invoke(ctx, {"capability_id": "roadmap.build",
                                                       "input": {"brief": brief}})
            assert first["ok"], first
            assert first["data"]["result"]["pending_action"]["items"][0]["field"] == "test_attempt[IELTS].overall_score"
            with student.factory() as db:
                candidate = MemoryCandidateService(db).propose(
                    student.workspace_id, "student_record", key="test_attempt",
                    proposed_value={"test_type": "IELTS", "overall_score": "7.5"},
                    source_type="conversation", confidence=0.95)
                assert MemoryReconciler(db).reconcile(candidate).accepted
                db.commit()
            second = await capability_tools.invoke(ctx, {"capability_id": "roadmap.build",
                                                        "input": {"brief": brief}})
            assert second["ok"], second
            assert second["data"]["result"]["pending_action"] is None
            assert second["data"]["result"]["roadmaps"][0]["gaps"][0]["status"] == "met"
            assert second["data"]["result"]["roadmaps"][0]["research_status"] == "proposed"
    finally:
        set_web_search_provider(None)
