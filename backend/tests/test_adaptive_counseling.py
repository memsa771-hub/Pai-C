"""Person-first policy and visible replies through the real pipeline, offline only.

Fake model outputs demonstrate routing/validation, not model counseling quality.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import BackgroundJob, CounselorNotedQuestion, CounselorTurnDecision, EventRecord, ExecutionRun
from app.pai_c import myths
from app.pai_c.deep.context import build_context, _trim_notebook
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.planner.patch import apply_patch, PatchRejected
from app.pai_c.planner.view import build_planner_view
from app.pai_c.policy.classifier import Signals, fallback_signals
from app.pai_c.policy.controller import decide
from app.pai_c.policy.state import first_picture_due
from app.pai_c.understanding.views import coverage_areas
from app.research.gateway import request_research
from app.tools import ToolContext
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn
from tests.test_policy_guided import state
from tests.truth_map_fixtures import item


def signals(**changes):
    return Signals.model_validate({**fallback_signals().model_dump(), **changes})


def reply(text):
    return json.dumps({"reply": text, "moves": ["reflect"], "action": {"type": "none"}})


@pytest.mark.asyncio
async def test_direct_information_empty_profile_queues_research_not_an_interview(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = signals(intent="asking_info", request={"text": "Tell me about Example University",
        "kind": "information", "needs_research": True, "needs_context": False})
    with StudentSession() as student:
        async def voice(**kwargs):
            with student.factory() as db:
                assert db.scalar(select(BackgroundJob.id).where(BackgroundJob.job_type == "research.claim")) is None
            return reply("I'll check current sources for that information.")
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", voice):
            await student.turn(sig.request.text)
        assert student.transcript[-1]["content"] == "I'll check current sources for that information."
        with student.factory() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim"))
            assert job and job.payload["request_id"]
            assert myths.enqueue_information(db, student.workspace_id, job.payload["source_event_id"]).id == job.id
            assert db.scalar(select(ExecutionRun.id)) is None
            assert await request_research("information", "another-workspace", db=db, journey=None,
                tool_context=ToolContext(workspace_id=student.workspace_id, agent_name="pai", api=None),
                refresh_key=job.payload["source_event_id"]) is None


@pytest.mark.asyncio
async def test_voice_promise_to_check_always_starts_research(monkeypatch):
    """Live audit: PAI said it would check official sources and nothing ran,
    because research started only on the policy's answer_request. When Voice
    itself notes a question for research, the check must start too."""
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = fallback_signals()
    question = "DAE Electronics fee range in Lahore"
    with StudentSession() as student:
        async def voice(**kwargs):
            return json.dumps({"reply": "I will check that from official sources.", "moves": ["give"],
                               "action": {"type": "note_question", "question_to_research": question}})
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())),              patch("app.pai_c.deep.turn.chat_completion", voice):
            await student.turn("Lahore mein electronics ke courses kitne ke hain?")
        with student.factory() as db:
            noted = db.scalar(select(CounselorNotedQuestion).where(CounselorNotedQuestion.question_to_research == question))
            assert noted is not None and noted.needs_research
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim"))
            assert job is not None and job.payload["request_id"] == noted.id
            # Idempotent: the policy path queuing the same request adds nothing.
            assert myths.enqueue_information(db, student.workspace_id, job.payload["source_event_id"]).id == job.id


@pytest.mark.asyncio
@pytest.mark.parametrize("text,response,areas", [
    ("I play football with friends after helping at home.", "There is room here for both your friendships and what life at home asks of you.", ["interests", "family_social"]),
    ("I help at the shop, study, and edit videos at night.", "Your days combine responsibilities, learning and something you choose for yourself.", ["status", "history", "interests", "family_social"]),
    ("My parent prefers a stable career for me.", "That is their preference. It does not tell me yet how you feel about it.", ["family_social", "goals"]),
    ("I used to want research; now time with family matters more.", "That changes what a good path needs to offer you. We can reconsider the earlier direction.", ["goals", "values"]),
    ("Mujhe doston ke sath khelna acha lagta hai.", "Doston ke sath waqt tumhari zindagi ka aik aham hissa lagta hai.", ["interests", "family_social"]),
])
async def test_personal_sharing_stays_in_domain_without_forced_questions(monkeypatch, text, response, areas):
    sig = signals(intent="sharing", mentioned_areas=areas, opened_thread=areas[0])
    # Education basics are known, so a hobby or family story alone does not earn a question.
    decision = decide(state(**sig.model_dump()))
    assert not decision.question_allowed
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=reply(response + " What else do you enjoy?"))
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, text), history=[], decision=decision, signals=sig)
        assert result.reply == response
        assert "question_removed" in result.guard_violations
        assert "count only as supporting evidence" in model.await_args.kwargs["system_prompt"]


def test_useful_clarification_not_a_fixed_ratio_and_safety_precedes_request():
    decision = decide(state(coverage={}, question_needed=True, questions_in_last_two=True))
    assert decision.question_allowed
    for index in range(4):
        assert not decide(state(question_needed=False, student_count=index + 1)).question_allowed
    assert decide(state(safety={"level": "urgent"}, request={"needs_context": True})).action == "care"


def addition(part, key, value, **extra):
    return {"op": "add", "part": part, "item": {"key": key, "value": value,
        "evidence": value, "kind": "said", "confidence": "medium", **extra}}


def test_rich_message_records_multiple_dimensions_without_inflated_ability():
    operations = [addition("world.daily_life", "day", "I study and edit videos"),
        addition("self", "interest.editing", "I like editing videos"),
        addition("world.responsibilities", "help", "I help in the family shop"),
        addition("world.social", "friends", "I play with friends"),
        addition("world.education_story", "project", "I completed a small project"),
        addition("self", "creative", "I am creative", capability_status="untested", level="claimed")]
    notebook = apply_patch(CounselorNotebookData(), operations, set(), "Student's account")
    covered = coverage_areas(notebook, SimpleNamespace(facts={}, records={}))
    assert all(covered[key]["item_count"] for key in ("status", "history", "interests", "family_social", "strengths"))
    assert notebook.self[-1].kind == "said" and notebook.self[-1].capability_status == "untested"
    assert notebook.world.education_story[0].kind == "said"


@pytest.mark.parametrize("kind", ["shown", "action", "document"])
def test_new_independent_evidence_requires_supported_reference(kind):
    operation = addition("shown", "project", "I completed a project", kind=kind, capability_status="demonstrated")
    with pytest.raises(PatchRejected):
        apply_patch(CounselorNotebookData(), [operation], set(), "I completed a project")
    operation["item"]["vault_fact_ref"] = "verified-record"
    result = apply_patch(CounselorNotebookData(), [operation], set(), "I completed a project", evidence_refs={"verified-record"})
    assert result.shown[0].vault_fact_ref == "verified-record"


def test_proven_level_cannot_bypass_demonstrated_capability_reference_check():
    with pytest.raises(PatchRejected):
        apply_patch(CounselorNotebookData(), [addition("self", "creative", "I am creative", level="proven")], set(), "I am creative")
    notebook = CounselorNotebookData.model_validate({"self": [item(id="claim")]})
    with pytest.raises(PatchRejected):
        apply_patch(notebook, [{"op": "update", "id": "claim", "fields": {
            "level": "proven", "evidence": "I am creative"}}], {"claim"}, "I am creative")


def test_family_wish_does_not_imply_pressure_or_control():
    notebook = apply_patch(CounselorNotebookData(), [{"op": "upsert_person", "role": "Parent",
        "wish": "Stable work", "evidence": "My parent prefers stable work"}], set(), "My parent prefers stable work")
    assert notebook.world.people[0].worry == "" and notebook.world.people[0].supportive is None
    assert notebook.pressures.items == []


def test_light_review_uses_active_evidence_without_compulsory_family_or_rating():
    notebook = CounselorNotebookData(depth_mode="light")
    result = apply_patch(notebook, [addition("said", "goal", "I want to learn"),
        addition("self", "interest", "I enjoy making things"),
        {"op": "set_coverage", "part": "said", "value": True},
        {"op": "set_coverage", "part": "self", "value": True}], set(), "I enjoy making things")
    assert result.mirror_ready and result.sure.score is None and not result.world.people
    retired = apply_patch(result, [{"op": "retire", "id": result.self[0].id,
        "reason": "Student corrected this"}], {result.self[0].id}, "That does not fit")
    assert not retired.mirror_ready


def test_reported_experience_can_support_tentative_possibility_without_verifying_ability():
    from app.pai_c.planner.plan import validate_plan
    notebook = CounselorNotebookData.model_validate({
        "shown": [item("I organized a community event", id="experience")],
        "self": [item("I enjoy coordinating people", id="interest")]})
    plan = validate_plan({"next_move": "tell", "intent": "Offer a possibility, not a conclusion",
        "target_gap": None, "give": "This may be worth exploring", "avoid_questions": [], "playbooks": [],
        "possibility": {"title": "Community coordination", "why": "You described organizing and enjoying coordination",
            "evidence_item_ids": ["experience", "interest"]}}, view=build_planner_view(notebook))
    assert plan.possibility and notebook.shown[0].kind == "said"


@pytest.mark.asyncio
async def test_pending_information_waits_for_care_without_repeating_research(monkeypatch):
    from app.jobs.service import JobDeferred
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = signals(intent="asking_info", request={"text": "Program information", "kind": "information",
        "needs_context": False, "needs_research": True})
    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", AsyncMock(return_value=reply("I'll check sources."))):
            await student.turn(sig.request.text)
        with student.factory() as db:
            decision = db.scalar(select(CounselorTurnDecision))
            decision.decision = {"action": "care"}
            db.commit()
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim"))
            checker = AsyncMock(return_value={"status": "unanswered"})
            with patch.object(myths, "_check_job", checker):
                with pytest.raises(JobDeferred):
                    await myths.check_job(job, db)
                assert db.scalar(select(CounselorNotedQuestion)).status == "open"
                decision.decision = {"action": "counsel"}
                db.commit()
                await myths.check_job(job, db)
            assert checker.await_count == 1
            assert db.scalar(select(CounselorNotedQuestion)).status == "unanswered"


def test_early_picture_depends_on_evidence_not_count_and_correction_is_retained():
    coverage = {key: {"covered": True} for key in ("status", "history", "interests", "family_social")}
    assert first_picture_due(coverage=coverage, student_count=2, prior_decisions=[], mirror_ready=False)
    assert not first_picture_due(coverage={}, student_count=200, prior_decisions=[], mirror_ready=False)
    before = CounselorNotebookData.model_validate({"self": [item(id="old", value="An old interpretation")]})
    after = apply_patch(before, [{"op": "retire", "id": "old", "reason": "Student rejected it"},
        addition("self", "value.changed", "I now value time with family")], {"old"}, "I now value time with family")
    assert "An old interpretation" not in json.dumps(_trim_notebook(after))
    assert after.self[0].status == "retired" and len(after.self) == 2


@pytest.mark.asyncio
async def test_research_result_delivered_once_with_source_and_available_before_mirror(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = signals(intent="asking_info", request={"text": "Which programs exist?", "kind": "information",
        "needs_context": False, "needs_research": True})
    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", AsyncMock(return_value=reply("I'll check sources."))):
            await student.turn(sig.request.text)
        with student.factory() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim"))
            fact = {"quote": "The catalog lists this program.", "value": "The catalog lists this program.",
                "source_url": "https://catalog.example.test/program", "checked_at": datetime.now(timezone.utc).isoformat(), "status": "verified"}
            with patch.object(myths, "_check_job", AsyncMock(return_value={"status": "sourced", "fact": fact})):
                await myths.check_job(job, db)
                await myths.check_job(job, db)
            posted = db.scalars(select(EventRecord).where(EventRecord.metadata_["information_job_id"].as_string() == job.id)).all()
            assert len(posted) == 1 and fact["source_url"] in posted[0].payload["content"]
            context = await build_context(db, student.workspace_id, _turn(student))
            assert context.world_facts[0]["fact_id"] == job.id
            assert myths.information_facts(db, "another-workspace") == []


@pytest.mark.asyncio
async def test_no_source_leaves_request_unanswered_and_does_not_invent_fact(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = signals(intent="asking_info", request={"text": "What is the entry requirement?", "kind": "information",
        "needs_context": False, "needs_research": True})
    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", AsyncMock(return_value=reply("I'll check that."))):
            await student.turn(sig.request.text)
        with student.factory() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim"))
            with patch.object(myths, "_check_job", AsyncMock(return_value={"status": "unanswered"})):
                await myths.check_job(job, db)
            request = db.scalar(select(CounselorNotedQuestion))
            assert request.status == "unanswered" and request.answer is None
            assert myths.information_facts(db, student.workspace_id) == []
            assert "couldn't verify" in student.transcript[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("draft,official,expected", [
    ({"quote": "A program is listed.", "source_url": "https://catalog.example.test/info"}, True, "sourced"),
    ({"quote": "An invented requirement.", "source_url": "https://catalog.example.test/info"}, True, "unanswered"),
    ({"quote": "A program is listed.", "source_url": "https://catalog.example.test/info"}, False, "unanswered"),
    ("broken-json", True, "unanswered"),
])
async def test_information_runs_existing_source_pipeline_with_fake_tools(draft, official, expected):
    from app.pai_c.deep.noted_questions import NotedQuestionService
    from app.research.requirements import RequirementStore
    from tests.test_counselor_deep_pr4 import _turn_job
    url = "https://catalog.example.test/info"
    executor = SimpleNamespace(execute=AsyncMock(side_effect=[
        {"ok": True, "data": {"results": [{"url": url}]}},
        {"ok": True, "data": {"url": url, "content": "A program is listed."}}]))
    with StudentSession() as student, student.factory() as db:
        _, event_id = _turn_job(student, db)
        NotedQuestionService(db).record(student.workspace_id, event_id,
            "What program is listed?", kind="information", needs_research=True, pending=True)
        job = myths.enqueue_information(db, student.workspace_id, event_id)
        with patch("app.tools.get_tool_executor", return_value=executor), \
             patch("app.inference.gateway.complete", AsyncMock(return_value=json.dumps(draft) if isinstance(draft, dict) else draft)), \
             patch.object(RequirementStore, "official_domains", return_value={"catalog.example.test"} if official else set()):
            result = await myths._check_job(job, db)
        assert result["status"] == expected
        assert [call.args[0] for call in executor.execute.await_args_list] == ["web.search", "web.fetch"]
        if expected == "sourced":
            assert result["fact"]["quote"] == "A program is listed." and result["fact"]["checked_at"]
        else:
            assert not result.get("fact")


# R-47 C3: every "I'll check" runs, or the student is told it couldn't.

QUESTION = "DAE Electronics fee range in Lahore"


def _research_signals(needs_research=True, **changes):
    return signals(intent="asking_info", request={"text": QUESTION, "kind": "information",
        "needs_context": False, "needs_research": needs_research}, **changes)


def _decision(action):
    from app.pai_c.policy.controller import Decision
    return Decision(rule_id="test", action=action, topic=None, question_allowed=False,
                    invite=False, summary_due=False)


async def _ask(student, sig, *, voice_action=None, decision=None, research=None):
    """One student turn through the real runtime with offline fakes."""
    async def voice(**kwargs):
        return json.dumps({"reply": "I will check that from official sources.", "moves": ["give"],
                           "action": voice_action or {"type": "none"}})
    patches = [patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())),
               patch("app.pai_c.deep.turn.chat_completion", voice)]
    if decision is not None:
        patches.append(patch("app.pai_c.policy.controller.decide", return_value=_decision(decision)))
    if research is not None:
        patches.append(patch("app.research.gateway.request_research", research))
    for item_patch in patches:
        item_patch.start()
    try:
        await student.turn("Lahore mein electronics ke courses kitne ke hain?")
    finally:
        for item_patch in reversed(patches):
            item_patch.stop()


def _claim_jobs(db):
    return db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim")).all()


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_classifier_recorded_question_starts_research_when_voice_note_is_duplicate(monkeypatch):
    """The classifier already saved the question, so Voice's note_question is a
    duplicate and the decision is not answer_request: the check still runs, once."""
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, _research_signals(), decision="counsel",
                   voice_action={"type": "note_question", "question_to_research": QUESTION})
        with student.factory() as db:
            noted = db.scalar(select(CounselorNotedQuestion))
            decision = db.scalar(select(CounselorTurnDecision))
            assert decision.move == "note_question" and decision.decision["action"] == "counsel"
            jobs = _claim_jobs(db)
            assert len(jobs) == 1 and jobs[0].payload["request_id"] == noted.id


@pytest.mark.req("R-47")
@pytest.mark.asyncio
@pytest.mark.parametrize("voice_type", ["none", "note_question"])
@pytest.mark.parametrize("decision", ["answer_request", "explore_area"])
async def test_recorded_question_starts_research_whatever_the_decision(monkeypatch, voice_type, decision):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    action = {"type": "note_question", "question_to_research": QUESTION} if voice_type == "note_question" else None
    with StudentSession() as student:
        await _ask(student, _research_signals(), decision=decision, voice_action=action)
        with student.factory() as db:
            noted = db.scalar(select(CounselorNotedQuestion))
            jobs = _claim_jobs(db)
            assert len(jobs) == 1 and jobs[0].payload["request_id"] == noted.id


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_research_starts_on_a_wellbeing_turn_and_delivery_waits_for_care(monkeypatch):
    from app.jobs.service import JobDeferred
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = _research_signals(safety={"level": "concern", "category": "acute_distress"})
    with StudentSession() as student:
        await _ask(student, sig)
        with student.factory() as db:
            assert db.scalar(select(CounselorTurnDecision)).move == "wellbeing"
            jobs = _claim_jobs(db)
            assert len(jobs) == 1
            checker = AsyncMock(return_value={"status": "unanswered"})
            with patch.object(myths, "_check_job", checker), pytest.raises(JobDeferred):
                await myths.check_job(jobs[0], db)
            assert db.scalar(select(CounselorNotedQuestion)).status == "open"


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_busy_research_start_is_retried_once(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    research = AsyncMock(side_effect=[{"ok": False, "error": {"code": "research_busy"}},
                                      {"ok": True, "data": {"job_id": "j"}}])
    with StudentSession() as student:
        await _ask(student, _research_signals(), research=research)
    assert research.await_count == 2
    assert all(call.args[0] == "information" for call in research.await_args_list)


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_busy_research_start_gives_up_after_one_retry(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    research = AsyncMock(return_value={"ok": False, "error": {"code": "research_busy"}})
    with StudentSession() as student:
        await _ask(student, _research_signals(), research=research)
        assert student.transcript[-1] == {"role": "assistant", "message_type": "chat",
                                          "content": "I will check that from official sources."}
    assert research.await_count == 2


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_research_start_that_raises_is_retried_once(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    research = AsyncMock(side_effect=[RuntimeError("database went away"), {"ok": True, "data": {"job_id": "j"}}])
    with StudentSession() as student:
        await _ask(student, _research_signals(), research=research)
        assert student.transcript[-1]["content"] == "I will check that from official sources."
    assert research.await_count == 2


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_question_without_research_need_starts_nothing(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    research = AsyncMock(return_value={"ok": True, "data": {"job_id": "j"}})
    with StudentSession() as student:
        await _ask(student, _research_signals(needs_research=False), research=research)
    research.assert_not_awaited()


def _open_question(student, db, *, age_minutes, now):
    from datetime import timedelta
    from app.pai_c.deep.noted_questions import NotedQuestionService
    from tests.test_counselor_deep_pr4 import _turn_job
    _, event_id = _turn_job(student, db)
    assert NotedQuestionService(db).record(student.workspace_id, event_id, QUESTION,
        kind="information", needs_research=True, pending=True) == "recorded"
    row = db.scalar(select(CounselorNotedQuestion).where(CounselorNotedQuestion.source_event_id == event_id))
    row.created_at = now - timedelta(minutes=age_minutes)
    db.commit()
    return row


def _notice_jobs(db):
    return db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "research.claim",
        BackgroundJob.idempotency_key.like("information-unanswered:%"))).all()


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_sweep_tells_the_student_after_30_minutes_without_a_job():
    from app.pai_c.policy.controller import load_data
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        row = _open_question(student, db, age_minutes=31, now=now)
        assert myths.sweep_unstarted_information(db, now=now) == 1
        [job] = _notice_jobs(db)
        assert job.payload == {"request_id": row.id, "source_event_id": row.source_event_id, "not_started": True}
        assert job.idempotency_key == f"information-unanswered:{student.workspace_id}:{row.id}"
        checker = AsyncMock(return_value={"status": "sourced"})
        with patch.object(myths, "_check_job", checker):
            assert (await myths.check_job(job, db)) == {"status": "not_started"}
            await myths.check_job(job, db)
        checker.assert_not_awaited()
        notice = load_data("myths.json")["information_unanswered"]
        assert [turn["content"] for turn in student.transcript].count(notice) == 1
        db.refresh(row)
        assert row.status == "unanswered" and row.answer is None


@pytest.mark.req("R-47")
@pytest.mark.asyncio
@pytest.mark.parametrize("age,started", [(29, None), (31, "pending"), (31, "running"), (31, "succeeded")])
async def test_sweep_leaves_recent_or_started_questions(age, started):
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        row = _open_question(student, db, age_minutes=age, now=now)
        if started:
            job = myths.enqueue_information(db, student.workspace_id, row.source_event_id)
            assert job.idempotency_key == f"information:{student.workspace_id}:{row.id}"
            job.status = started
            db.commit()
        assert myths.sweep_unstarted_information(db, now=now) == 0
        assert _notice_jobs(db) == []


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_sweep_covers_a_failed_research_job():
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        row = _open_question(student, db, age_minutes=31, now=now)
        job = myths.enqueue_information(db, student.workspace_id, row.source_event_id)
        job.status = "failed"
        db.commit()
        assert myths.sweep_unstarted_information(db, now=now) == 1


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_sweep_skips_answered_and_non_information_questions():
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        answered = _open_question(student, db, age_minutes=31, now=now)
        answered.status = "unanswered"
        task = _open_question(student, db, age_minutes=31, now=now)
        task.kind = "task"
        db.commit()
        assert myths.sweep_unstarted_information(db, now=now) == 0


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_sweep_is_idempotent():
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        _open_question(student, db, age_minutes=31, now=now)
        assert myths.sweep_unstarted_information(db, now=now) == 1
        assert myths.sweep_unstarted_information(db, now=now) == 0
        assert len(_notice_jobs(db)) == 1


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_session_sweep_runs_the_information_sweep():
    from app.pai_c.sessions import sweep_job
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        _open_question(student, db, age_minutes=31, now=now)
        result = await sweep_job(SimpleNamespace(payload={}), db)
        assert result["information_notices"] == 1
        assert len(_notice_jobs(db)) == 1
