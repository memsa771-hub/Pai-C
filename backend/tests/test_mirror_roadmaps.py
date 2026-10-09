"""Confirmed Mirror -> facts -> grounded lane cards, entirely offline."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.counseling.deep.roadmaps import FIT_FIELDS, build_mirror_roadmaps, ground_roadmap, lanes_for_mirror
from app.journey import JourneyService
from app.models import CounselorNotedQuestion, EventRecord, ExecutionRun, Opportunity, RequirementSet, Roadmap, StudentJourney
from app.research.requirements import RequirementStore
from app.roadmaps.service import RoadmapService
from scripts.counselor_eval_support import StudentSession
from datetime import datetime, timezone


def example():
    mirror = json.loads((Path(__file__).parent / "fixtures/mirror/valid.json").read_text())
    roadmaps = [{"lane": lane["lane"], "title": lane["why"],
        **{key: ["Practical work"] if key == "strengths_used" else "Based on your described experience"
           for key in FIT_FIELDS}, "gap": [{"need": "Completed study", "have": "Student-reported study", "gap": "Check documents"}],
        "steps": [], "risks": [], "facts": [], "citations": {"gap.0.need": ["fact"]}, "status": "ready"}
        for lane in mirror["roadmap_lanes"]]
    return mirror, roadmaps


def test_unsourced_number_is_removed_and_marked_needs_info():
    mirror, cards = example()
    card = cards[0] | {"why_for_you": "A fee of 5000 applies."}
    output = ground_roadmap(card, mirror["roadmap_lanes"][0], {}, {"lanes": []})
    assert output["generation_status"] == "needs_info"
    assert output["why_for_you"] == ""
    assert any(item["field"] == "why_for_you" for item in output["missing_facts"])


def test_original_dream_retained_as_a_test_lane():
    mirror, _ = example()
    mirror["roadmap_lanes"] = [item for item in mirror["roadmap_lanes"] if item["lane"] != "test_the_dream"]
    mirror["roadmap_lanes"].append({"lane": "family_wish", "why": "A separate family wish"})
    from app.counseling.deep.mirror_schema import CounselorMirror
    with pytest.raises(ValueError, match="original-dream"):
        CounselorMirror.model_validate(mirror)
    assert lanes_for_mirror(mirror) == mirror["roadmap_lanes"]


@pytest.mark.asyncio
async def test_one_grounded_card_per_lane_questions_sourced_and_publication_idempotent():
    with StudentSession() as student, student.factory() as db:
        mirror, cards = example()
        journeys = JourneyService(db); journey = journeys.ensure_counselor(student.workspace_id)
        for stage in ("FOUNDATION", "DIRECTION", "MIRROR", "RESEARCHING", "ASSESSING"):
            journey = journeys.set_counselor_stage(student.workspace_id, journey.id, stage)
        row = db.get(StudentJourney, journey.id)
        row.counselor_summary_draft = {"type": "mirror", "status": "confirmed", "version": 1, "mirror": mirror}
        event = EventRecord(id=str(uuid4()), network_id=student.workspace_id, type="workspace.message.posted",
            source=f"human:{student.user_id}", target="channel/pai-counselor", payload={"content": "What is needed?"}, timestamp=1)
        db.add(event); db.flush()
        question = CounselorNotedQuestion(workspace_id=student.workspace_id, source_event_id=event.id,
                                          question_to_research="What is needed?")
        db.add(question); db.flush()
        opportunity = Opportunity(id=str(uuid4()), workspace_id=student.workspace_id, route={}, country="fixture", url="https://official.example/route")
        evidence = RequirementSet(id=str(uuid4()), opportunity_id=opportunity.id,
            source_url=opportunity.url, checked_at=datetime.now(timezone.utc), status="verified", version=1,
            rules=[{"field": key, "decisive_field": key, "value": "Completed study", "quote": "Completed study is required",
                    "source_url": opportunity.url} for key in ("eligibility", "required_tests", "cost_range", "intake_window")], fees={}, deadlines={})
        db.add_all([opportunity, evidence]); db.commit()
        facts = [{**item, "label": "verified", "requirement_set_id": evidence.id}
                 for item in RequirementStore.payload(opportunity, evidence)["rules"]]
        for card in cards: card["citations"]["gap.0.need"] = [item["fact_id"] for item in facts]
        brief = {"mirror": mirror, "mirror_version": 1, "notebook": {}, "profile": {},
                 "questions": [{"id": question.id, "question": question.question_to_research}]}
        research = {"lanes": [{"lane": item["lane"], "facts": facts} for item in mirror["roadmap_lanes"]],
                    "decisive_fields": [item["field"] for item in facts]}
        raw = {"roadmaps": cards, "question_answers": [{"question_id": question.id, "fact_id": facts[0]["fact_id"]}]}
        with patch("app.counseling.deep.roadmaps.chat_completion", AsyncMock(return_value=json.dumps(raw))) as model:
            artifact = await build_mirror_roadmaps(brief, research)
        model.assert_awaited_once()
        assert len(artifact["roadmaps"]) == len(mirror["roadmap_lanes"])
        assert all(item["generation_status"] == "ready" for item in artifact["roadmaps"])
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai", objective="Research",
            task_type="roadmap_research", status="completed", constraints={"research_key": journey.id + ":mirror:1",
            "mirror_version": 1, "capability_input": {"brief": brief}}, result={"capability_result": artifact})
        db.add(run); db.commit()
        service = RoadmapService(db)
        ids = service.publish_from_run(run); db.commit()
        assert service.publish_from_run(run) == ids
        assert len(db.scalars(select(Roadmap)).all()) == len(cards)
        db.refresh(question)
        assert question.status == "answered" and question.fact_id == facts[0]["fact_id"]
        assert question.answer["source_url"] == opportunity.url
        serialized = service.get(student.workspace_id, ids[0])
        assert serialized["why_for_you"] and serialized["test_30_days"]
        assert serialized["your_questions"][0]["answer"] == facts[0]["quote"]
        from app.plugins.roadmap_builder import on_run_status
        on_run_status(db, run)
        assert journeys.get(student.workspace_id, journey.id).current_stage == "PROPOSED"
        row.counselor_summary_draft = {**row.counselor_summary_draft, "version": 2}
        db.flush()
        assert service.publish_from_run(run) == []

@pytest.mark.asyncio
async def test_budget_exhaustion_publishes_missing_lane_facts_without_model_call():
    from app.config import config
    from app.plugins._shared.budget import bounded_research
    mirror, _ = example()
    with StudentSession() as student, patch.object(config, 'PAI_RESEARCH_MAX_CALLS_PER_STUDENT', 0):
        with bounded_research(queries=5, fetches=5, seconds=30, workspace_id=student.workspace_id):
            with patch('app.counseling.deep.roadmaps.chat_completion', AsyncMock()) as model:
                result = await build_mirror_roadmaps({'mirror': mirror, 'mirror_version': 1,
                    'notebook': {}, 'profile': {}}, {'lanes': [], 'decisive_fields': ['eligibility']})
        model.assert_not_awaited()
    assert len(result['roadmaps']) == len(mirror['roadmap_lanes'])
    assert all(row['generation_status'] == 'needs_info' for row in result['roadmaps'])
    assert all(any(item['field'] == 'eligibility' for item in row['missing_facts']) for row in result['roadmaps'])


def test_operator_gate_requires_confirmed_current_mirror_version():
    from app.services.operator import _baseline_is_current, _result_context_current
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by='test',
            objective='Research', task_type='roadmap_research', status='completed', constraints={'mirror_version': 2})
        assert not _baseline_is_current(db, student.workspace_id)
        row = db.get(StudentJourney, journey.id)
        row.counselor_summary_draft = {'type':'mirror','status':'confirmed','version':2}
        db.flush()
        assert _baseline_is_current(db, student.workspace_id)
        assert _result_context_current(db, run)
        run.constraints = {'mirror_version':1}
        assert not _result_context_current(db, run)
        row.counselor_summary_draft = {**row.counselor_summary_draft, 'status':'needs_changes'}
        db.flush()
        assert not _baseline_is_current(db, student.workspace_id)


def test_dream_test_never_silently_replaces_another_confirmed_lane():
    mirror, _ = example()
    mirror['roadmap_lanes'] = [item for item in mirror['roadmap_lanes'] if item['lane'] != 'test_the_dream']
    mirror['roadmap_lanes'] += [{'lane':'family_wish','why':'A distinct family direction'},
                               {'lane':'another_route','why':'Another student direction'}]
    from app.counseling.deep.mirror_schema import CounselorMirror
    with pytest.raises(ValueError, match='original-dream'):
        CounselorMirror.model_validate(mirror)
    assert lanes_for_mirror(mirror) == mirror['roadmap_lanes']

@pytest.mark.asyncio
async def test_sourced_question_cannot_render_a_config_blocked_script():
    from app.config import config
    mirror, _ = example()
    fact = {'fact_id':'fact','quote':chr(0x0905),'label':'verified',
            'source_url':'https://official.example/route'}
    brief = {'mirror':mirror, 'mirror_version':1, 'notebook':{}, 'profile':{},
             'questions':[{'id':'question','question':'What is required?'}]}
    raw = {'roadmaps':[], 'question_answers':[{'question_id':'question','fact_id':'fact'}]}
    with patch.object(config, 'PAI_LANGUAGE_BLOCKED_SCRIPTS', 'Devanagari'), \
         patch('app.counseling.deep.roadmaps.chat_completion', AsyncMock(return_value=json.dumps(raw))):
        result = await build_mirror_roadmaps(brief, {'lanes':[], 'question_facts':[fact]})
    assert result['question_answers'] == []
