"""Research provenance, registration, deterministic gaps and review states."""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.capabilities import get_capability_registry
from app.plugins.gap_assessment import assess_rule
from app.plugins.qualification_recognition import marks_percentage, recognize
from app.plugins._shared.institution_registry import registry_identity
from app.plugins.program_research import research as research_program
from app.plugins.roadmap_builder import build, on_run_status
from app.journey import JourneyService
from app.memory.handlers import resume_research
from app.models import BackgroundJob, EventRecord, ExecutionRun, Institution, MemoryCandidate
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.research.requirements import RequirementStore, ResearchEvidenceError
from app.services import operator
from app.tools import AUDIENCE_OPERATOR, ToolContext
from app.tools.builtin import capabilities as capability_tools
from app.tools.web_search import set_web_search_provider
from app.memory.permissions import OPERATOR_CAPABILITIES
from scripts.counselor_eval_support import StudentSession


def test_six_research_capabilities_register_with_single_owners():
    registry = get_capability_registry()
    expected = {"program.discover", "program.research", "qualification.recognize",
                "scholarship.discover", "gap.assess", "roadmap.build"}
    assert {item.id for item in registry.all()} == expected
    assert registry.owner_for_task_type("roadmap_research").id == "roadmap.build"
    assert registry.get("roadmap.build").uses_capabilities == expected - {"roadmap.build"}


def test_registry_identity_requires_a_unique_active_website_match():
    record = {"status": "active", "id": "https://ror.org/012345678",
              "names": [{"value": "Example University", "types": ["ror_display"]}],
              "locations": [{"geonames_details": {"country_code": "DE"}}],
              "links": [{"type": "website", "value": "https://example.edu"}]}
    assert registry_identity("https://admissions.example.edu/program", {"items": [record]})["domains"] == ["example.edu"]
    assert registry_identity("https://example.edu.evil.test/program", {"items": [record]}) is None
    assert registry_identity("https://example.edu/program", {"items": [record, record]}) is None


def test_requirement_store_requires_source_and_verifies_only_correlated_official_evidence():
    with StudentSession() as student, student.factory() as db:
        store = RequirementStore(db)
        now = datetime.now(timezone.utc)
        observed = now - timedelta(minutes=2)
        db.add(Institution(name="Example University", normalized_name="example university",
                           country_code="DE", website_url="https://example.edu",
                           source="catalog", provider="recorded_fixture", provider_id="example"))
        db.flush()
        assert store.institution_for_url("https://admissions.example.edu/cs") == "Example University"
        with pytest.raises(ResearchEvidenceError, match="source URL"):
            store.propose(student.workspace_id, route={}, country="Germany", source_url="http://example.com",
                          checked_at=now, rules=[])
        with pytest.raises(ResearchEvidenceError, match="Every rule"):
            store.propose(student.workspace_id, route={}, country="Germany", source_url="https://example.edu",
                          checked_at=now, rules=[{"field": "test.score"}])
        fact = {"kind": "requirement", "field": "test.score", "source_url": "https://example.edu/cs",
                "value": 7, "quote": "IELTS 7", "checked_at": observed.isoformat(),
                "comparator": "gte", "threshold": 7, "unit": "IELTS band"}
        opportunity, unconfirmed = store.propose(
            student.workspace_id, route={"program": "CS"}, country="Germany",
            institution="Example University", source_url="https://example.edu/cs",
            checked_at=observed, rules=[fact], intake="2027-fall", page_text="IELTS 7 for 2027")
        assert unconfirmed.status == "unconfirmed"
        assert unconfirmed.verification_checks["agreement"]["passed"] is False
        assert store.preferred(student.workspace_id, opportunity.id).id == unconfirmed.id
        assert store.preferred("another-workspace", opportunity.id) is None
        _, revision = store.propose(
            student.workspace_id, opportunity_id=opportunity.id,
            route={"program": "CS"}, country="Germany", intake="2027-fall",
            source_url="https://example.edu/cs", checked_at=observed, rules=[fact],
            page_text="IELTS 7 for 2027", corroboration=[{**fact, "source_url": "https://example.edu/admissions",
                                                              "checked_at": now.isoformat()}],
            corroborated_at=now)
        assert revision.version == 2
        assert revision.status == "verified"
        assert store.preferred(student.workspace_id, opportunity.id).id == revision.id
        reported = store.report_wrong_info(student.workspace_id, revision.id)
        assert reported.status == "unconfirmed"
        assert reported.verification_checks["student_report"]["passed"] is False
        assert db.execute(select(BackgroundJob).where(
            BackgroundJob.job_type == "research.refresh_stale")).scalar_one()
        assert db.execute(select(EventRecord).where(
            EventRecord.type == "research.requirement.reported")).scalar_one()
        db.commit()


def test_due_verification_sweep_invalidates_stale_fact_and_queues_refresh():
    from app.research.scheduler import enqueue_due_verification

    with StudentSession() as student, student.factory() as db:
        checked = datetime.now(timezone.utc) - timedelta(days=32)
        _, row = RequirementStore(db).propose(
            student.workspace_id, route={"program": "CS"}, country="Germany",
            source_url="https://example.edu/cs", checked_at=checked,
            rules=[{"field": "test.score", "source_url": "https://example.edu/cs",
                    "value": 7, "quote": "IELTS 7", "checked_at": checked.isoformat()}])
        row.status = "verified"
        db.flush()
        assert enqueue_due_verification(db, now=datetime.now(timezone.utc)) == 1
        assert row.status == "unconfirmed"
        assert db.execute(select(BackgroundJob).where(
            BackgroundJob.job_type == "research.refresh_stale")).scalar_one()
        assert enqueue_due_verification(db, now=datetime.now(timezone.utc)) == 0


@pytest.mark.asyncio
async def test_recorded_official_pages_can_auto_verify_program_fact():
    with StudentSession() as student:
        with student.factory() as db:
            db.add(Institution(name="Example University", normalized_name="example university",
                               country_code="DE", website_url="https://example.edu",
                               source="catalog", provider="recorded_fixture", provider_id="example-program"))
            db.commit()

        async def fetch(name, args):
            assert name == "web.fetch"
            return {"ok": True, "data": {"url": args["url"],
                    "content": "Winter 2027: IELTS overall 7 is required."}}

        fact = {"field": "test_attempt[IELTS].overall_score", "value": 7,
                "quote": "IELTS overall 7", "kind": "requirement",
                "comparator": "gte", "threshold": 7, "unit": "IELTS band"}
        context = SimpleNamespace(workspace_id=student.workspace_id,
                                  tools=SimpleNamespace(invoke=AsyncMock(side_effect=fetch)))
        with patch("app.inference.client.chat_completion",
                   new=AsyncMock(return_value=json.dumps({"facts": [fact]}))), \
                patch("app.plugins._shared.institution_registry.resolve_institution",
                      new=AsyncMock(return_value=None)):
            result = await research_program(context, {
                "url": "https://example.edu/program", "corroborating_url": "https://example.edu/admissions",
                "country": "Germany", "level": "master", "intake": "winter 2027",
                "route": {"program": "CS"}})
        assert result["requirements"][0]["status"] == "verified"
        assert all(item["passed"] for item in result["requirements"][0]["verification_checks"].values())


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


def test_marks_conversion_uses_awarded_total_and_never_guesses_from_cgpa():
    assert marks_percentage({"marks_obtained": 844, "marks_total": 1100}) == 76.73
    assert marks_percentage({"marks_obtained": 1200, "marks_total": 1100}) is None
    assert marks_percentage({"cgpa": 3.4, "cgpa_scale": 4}) is None


def test_research_run_stage_hook_follows_server_transition_graph():
    with StudentSession() as student, student.factory() as db:
        journeys = JourneyService(db)
        journey = journeys.ensure_counselor(student.workspace_id)
        for stage in ("FOUNDATION", "DIRECTION", "MIRROR", "RESEARCHING"):
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


def test_failed_research_publishes_retryable_card_and_leaves_assessing():
    with StudentSession() as student, student.factory() as db:
        journeys = JourneyService(db)
        journey = journeys.ensure_counselor(student.workspace_id)
        for stage in ("FOUNDATION", "DIRECTION", "MIRROR", "RESEARCHING", "ASSESSING"):
            journey = journeys.set_counselor_stage(student.workspace_id, journey.id, stage)
        run = ExecutionRun(workspace_id=student.workspace_id,
                           requested_by="openagents:pai", objective="Research",
                           task_type="roadmap_research", status="failed",
                           constraints={"research_key": f"{journey.id}:goal",
                                        "capability_input": {"brief": {
                                            "stated_preference": "CS in Germany",
                                            "underlying_objective": "tech career", "country": "Germany"}}},
                           result={"capability_result": {"roadmaps": [], "unconfirmed": [
                               {"reason": "Search provider unavailable"}]}})
        db.add(run)
        db.flush()
        on_run_status(db, run)
        assert journeys.get(student.workspace_id, journey.id).current_stage == "PROPOSED"
        from app.pai_c.roadmaps.service import RoadmapService
        card = RoadmapService(db).for_run(student.workspace_id, run.id)[0]
        assert card["generation_status"] == "failed"


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
                patch("app.research.gateway.request_research",
                      AsyncMock(return_value=None)):
            outcome = await resume_research(SimpleNamespace(
                workspace_id=student.workspace_id, payload={"candidate_id": candidate.id}), db)
        assert outcome["resumed"] == 1
        assert resumed.await_args.args[1] == run.id
        assert resumed.await_args.args[2] == {"candidate_id": candidate.id}
