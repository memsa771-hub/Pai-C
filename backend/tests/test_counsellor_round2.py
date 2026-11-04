# -*- coding: utf-8 -*-
"""P0 round 2 fixes after the live run of 2026-11-04 (R-47, design 5.5)."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.planner.patch import apply_patch, PatchRejected
from scripts.counselor_eval_support import StudentSession
from scripts.eval.recorded_planner import PLAN
from tests.test_counselor_deep_pr4 import _turn_job
from tests.test_counselor_planner import new_item


# R2-3: a rejected patch says why, as a fixed reason code, never student text.

@pytest.mark.req("R-47")
def test_r2_3_rejection_names_reason_code_op_index_and_part():
    before = CounselorNotebookData()
    ops = [{"op": "add", "part": "source", "item": new_item(value="private student text", category="self")},
           {"op": "add", "part": "said", "item": new_item(value="private student text")},
           {"op": "set_coverage", "part": "shown", "value": True}]
    with pytest.raises(PatchRejected) as raised:
        apply_patch(before, ops, frozenset(), "")
    message = str(raised.value)
    assert "op_index=2" in message
    assert "reason=coverage_without_evidence" in message
    assert "part=shown" in message
    assert "private student text" not in message
    assert raised.value.reason == "coverage_without_evidence"


@pytest.mark.req("R-47")
@pytest.mark.parametrize("op, reason", [
    ({"op": "confirm", "id": "unknown", "evidence": "private student text"}, "id_not_visible"),
    ({"op": "set_sure", "score": 7, "reason": "r", "would_raise": "w", "evidence": "e"}, "rating_not_in_student_text"),
    ({"op": "add", "part": "said", "item": new_item(category="self")}, "category_source_only"),
    ({"op": "add", "part": "said", "item": new_item(kind="shown")}, "evidence_needs_profile_ref"),
    ({"op": "add", "part": "said", "item": new_item(value="private student text", id="x")}, "invalid_operation"),
    ({"op": "unknown"}, "invalid_operation"),
])
def test_r2_3_each_rejection_has_a_fixed_reason(op, reason):
    with pytest.raises(PatchRejected) as raised:
        apply_patch(CounselorNotebookData(), [op], frozenset(), "")
    assert f"reason={reason}" in str(raised.value)
    assert "private student text" not in str(raised.value)


@pytest.mark.req("R-47")
def test_r2_3_non_list_patch_has_reason():
    with pytest.raises(PatchRejected) as raised:
        apply_patch(CounselorNotebookData(), {"op": "x"}, frozenset(), "")
    assert "reason=patch_not_a_list" in str(raised.value)


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_3_retry_feedback_to_the_analyst_carries_the_reason(caplog):
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        bad = {"patch": [{"op": "add", "part": "source", "item": new_item(value="private student text", category="self")},
                         {"op": "set_coverage", "part": "said", "value": True}],
               "plan": PLAN}
        good = {"patch": [{"op": "add", "part": "said", "item": new_item(value="Corrected")},
                          {"op": "set_coverage", "part": "said", "value": True}],
                "plan": PLAN}
        model = AsyncMock(side_effect=[json.dumps(bad), json.dumps(good)])
        from app.pai_c.deep.analysis import analyze_job
        with patch("app.pai_c.deep.analysis.chat_completion", model):
            await analyze_job(job, db)
    feedback = model.await_args_list[1].kwargs["system_prompt"]
    assert "op_index=1" in feedback
    assert "reason=coverage_without_evidence" in feedback and "part=said" in feedback
    assert "private student text" not in feedback
    assert "private student text" not in caplog.text


# R2-2: Voice's note_question ("I'll check") always leaves an open research question.

def _signals_with_request(kind, needs_research):
    from tests.test_adaptive_counseling import QUESTION, signals
    return signals(intent="asking_info", request={"text": QUESTION, "kind": kind,
        "needs_context": False, "needs_research": needs_research})


@pytest.mark.req("R-47")
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["information", "task"])
@pytest.mark.parametrize("decision", ["answer_request", "counsel"])
async def test_r2_2_voice_note_question_starts_research_even_when_classifier_said_no(monkeypatch, kind, decision):
    from app.config import config
    from app.models import CounselorNotedQuestion
    from sqlalchemy import select
    from tests.test_adaptive_counseling import QUESTION, _ask, _claim_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, _signals_with_request(kind, False), decision=decision,
                   voice_action={"type": "note_question", "question_to_research": QUESTION})
        with student.factory() as db:
            [noted] = db.scalars(select(CounselorNotedQuestion)).all()
            assert (noted.kind, noted.needs_research, noted.status) == ("information", True, "open")
            assert noted.answered_event_id is None
            jobs = _claim_jobs(db)
            assert len(jobs) == 1
            assert jobs[0].idempotency_key == f"information:{student.workspace_id}:{noted.id}"


@pytest.mark.req("R-47")
@pytest.mark.asyncio
@pytest.mark.parametrize("voice_flags, starts", [
    ({"kind": "task"}, True),                             # Voice's own default: research
    ({"kind": "task", "needs_research": True}, True),
    ({"kind": "task", "needs_research": False}, False),   # answered on the spot: no promise
])
async def test_r2_2_voice_note_without_classifier_request_follows_voices_research_flag(monkeypatch, voice_flags, starts):
    from app.config import config
    from app.models import CounselorNotedQuestion
    from app.pai_c.policy.classifier import fallback_signals
    from sqlalchemy import select
    from tests.test_adaptive_counseling import QUESTION, _ask, _claim_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, fallback_signals(), voice_action={"type": "note_question",
                   "question_to_research": QUESTION, **voice_flags})
        with student.factory() as db:
            noted = db.scalar(select(CounselorNotedQuestion))
            assert len(_claim_jobs(db)) == (1 if starts else 0)
            assert noted.status == ("open" if starts else "answered_now")


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_2_answered_request_without_note_question_stays_answered_now(monkeypatch):
    from app.config import config
    from app.models import CounselorNotedQuestion
    from sqlalchemy import select
    from tests.test_adaptive_counseling import _ask, _claim_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, _signals_with_request("information", False), decision="answer_request")
        with student.factory() as db:
            assert db.scalar(select(CounselorNotedQuestion)).status == "answered_now"
            assert _claim_jobs(db) == []


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_2_sweep_tells_the_student_when_the_start_failed(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.config import config
    from app.models import CounselorNotedQuestion
    from app.pai_c import myths
    from sqlalchemy import select
    from tests.test_adaptive_counseling import QUESTION, _ask, _claim_jobs, _notice_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    research = AsyncMock(side_effect=RuntimeError("database went away"))
    now = datetime.now(timezone.utc)
    with StudentSession() as student:
        await _ask(student, _signals_with_request("information", False), decision="answer_request",
                   voice_action={"type": "note_question", "question_to_research": QUESTION}, research=research)
        assert research.await_count == 2
        with student.factory() as db:
            assert _claim_jobs(db) == []
            row = db.scalar(select(CounselorNotedQuestion))
            row.created_at = now - timedelta(minutes=31)
            db.commit()
            assert myths.sweep_unstarted_information(db, now=now) == 1
            [notice] = _notice_jobs(db)
            assert notice.idempotency_key == f"information-unanswered:{student.workspace_id}:{row.id}"


# R2-1: strengths count toward the Mirror's interests (owner decision P0-D15).

def _mirror_basics(student, db):
    from tests.counselor_fixtures import prepare
    from tests.test_mirror_engine import _education, _record
    turn, journey, _ = prepare(student, db)
    _education(db, student.workspace_id)
    _record(db, student.workspace_id, "goal", {"goal_type": "study", "title": "Medicine"})
    student.prepared_event_id = turn.source_event_id
    return journey


def _write_notebook(student, db, parts):
    from app.pai_c.deep.notebook import NotebookService
    from tests.truth_map_fixtures import item
    NotebookService(db).apply(student.workspace_id, {
        "said": [item("I study and work on practical projects.", key="daily_life")], "mirror_ready": True,
        **parts}, student.prepared_event_id, expected_version=1)
    db.commit()


def _stage(db, journey_id):
    from app.models import StudentJourney
    db.expire_all()
    return db.get(StudentJourney, journey_id).current_stage


@pytest.mark.req("R-47")
def test_r2_1_two_notebook_strengths_cover_interests_and_ready_the_mirror():
    from app.pai_c.journey_sync import sync_counselor_stage
    from app.pai_c.mirror import MirrorEngine
    from app.pai_c.mirror.engine import ready_from
    from app.pai_c.memory import MemoryService
    from tests.truth_map_fixtures import item
    from tests.test_roadmap_engine import add_path, field_title
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        journey = _mirror_basics(student, db)
        assert not MirrorEngine(db).ready(ws)
        _write_notebook(student, db, {"self": [
            item("Biology is my strongest subject", key="strength.biology", id="s1"),
            item("Stays calm under pressure", key="strength.calm", id="s2")]})
        coverage = MemoryService(db).coverage_areas(ws)
        assert coverage["interests"]["covered"] and coverage["interests"]["item_count"] == 2
        assert MirrorEngine(db).ready(ws)
        assert sync_counselor_stage(db, ws, reason="analyst") == "MIRROR"
        db.commit()
        add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        assert sync_counselor_stage(db, ws, reason="paths") == "PROPOSED"
        db.commit()
        assert _stage(db, journey.id) == "PROPOSED"
        assert ready_from(coverage)


@pytest.mark.req("R-47")
def test_r2_1_two_vault_strength_items_move_direction_to_mirror():
    from app.pai_c.mirror import MirrorEngine
    from tests.test_mirror_gate_removed import accept_item
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        journey = _mirror_basics(student, db)
        accept_item(db, ws, "strength", {"text": "Biology is my strongest subject"})
        assert not MirrorEngine(db).build(ws)["ready"]
        accept_item(db, ws, "strength", {"text": "Stays calm under pressure"})
        assert MirrorEngine(db).build(ws)["ready"]
        assert _stage(db, journey.id) == "MIRROR"


@pytest.mark.req("R-47")
def test_r2_1_a_strength_and_an_interest_add_up_but_one_strength_alone_does_not():
    from app.pai_c.understanding.views import coverage_areas
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from types import SimpleNamespace
    from tests.truth_map_fixtures import item
    empty = SimpleNamespace(facts={}, records={})
    one = CounselorNotebookData.model_validate({"self": [item("Biology", key="strength.biology", id="s1")]})
    assert not coverage_areas(one, empty)["interests"]["covered"]
    both = CounselorNotebookData.model_validate({"self": [item("Biology", key="strength.biology", id="s1"),
                                                           item("Drawing", key="interest.drawing", id="i1")]})
    assert coverage_areas(both, empty)["interests"]["covered"]


# R2-4: an area asked and ignored is not asked a third time in a row.

def _ask_row(event_id, topic, items):
    return {"event_id": event_id, "decision": {"action": "explore_area", "topic": topic,
            "question_allowed": True, "topic_items": items, "signals": {}}}


def _round2_state(prior, interests_items, **changes):
    from types import SimpleNamespace
    from app.pai_c.policy.classifier import fallback_signals
    from app.pai_c.policy.state import derive_state
    from tests.test_policy_guided import AREAS, state
    coverage = {area: {"covered": True, "item_count": 2} for area in AREAS}
    coverage["interests"] = {"covered": False, "item_count": interests_items, "min_items": 2}
    coverage["status"] = {"covered": False, "item_count": 0, "min_items": 1}
    signals = fallback_signals().model_copy(update=changes)
    ordinals = {row["event_id"]: index + 1 for index, row in enumerate(prior)}
    ordinals["now"] = len(ordinals) + 1
    derived = derive_state(signals, coverage=coverage, mirror_ready=False, plan=SimpleNamespace(give=""),
        student_count=10, prior_decisions=prior, replies=["Statement."] * 2,
        student_ordinals=ordinals, current_event_id="now")
    return state(**{**derived, "student_count": 10, "summary_due": False, "first_picture_due": False,
                    "invite_pending": False, "questions_in_last_two": False})


@pytest.mark.req("R-47")
def test_r2_4_two_asks_without_new_coverage_cool_the_area_down():
    from app.pai_c.policy import controller
    prior = [_ask_row("e1", "interests", 0), _ask_row("e2", "interests", 0)]
    current = _round2_state(prior, 0, question_needed=True)
    assert current["stalled_areas"] == ["interests"]
    decision = controller.decide(current)
    assert decision.topic != "interests"
    assert (decision.action, decision.topic) == ("explore_area", "status")
    # With nothing else worth a question PAI counsels instead of repeating it.
    quiet = controller.decide(_round2_state(prior, 0))
    assert quiet.topic != "interests"


@pytest.mark.req("R-47")
@pytest.mark.parametrize("prior, items", [
    ([_ask_row("e1", "interests", 0), _ask_row("e2", "interests", 0)], 1),   # gained an entry
    ([_ask_row("e1", "goals", 0), _ask_row("e2", "interests", 0)], 0),       # asked only once
    ([_ask_row("e1", "interests", 0)], 0),
    ([_ask_row("e1", "interests", 0), _ask_row("e2", "interests", 0),
      {"event_id": "e3", "decision": {"action": "counsel", "topic": None}}], 0),  # cooled for one turn only
])
def test_r2_4_an_area_that_gained_coverage_or_was_not_repeated_is_asked(prior, items):
    from app.pai_c.policy import controller
    current = _round2_state(prior, items)
    assert current["stalled_areas"] == []
    assert (controller.decide(current).action, controller.decide(current).topic) == ("explore_area", "interests")


@pytest.mark.req("R-47")
def test_r2_4_decision_log_keeps_the_asked_area_entry_count_only():
    import json as _json
    from app.pai_c.policy import controller
    from app.pai_c.policy.classifier import fallback_signals
    from app.pai_c.policy.state import decision_log
    current = _round2_state([], 1)
    decision = controller.decide(current)
    assert decision.topic == "interests"
    record = decision_log(decision, fallback_signals(), coverage=current["coverage"])
    assert record["topic_items"] == 1
    other = controller.Decision(rule_id="counsel", action="counsel", topic=None, question_allowed=False,
                                invite=False, summary_due=False)
    assert "topic_items" not in decision_log(other, fallback_signals(), coverage=current["coverage"])
    assert "topic_items" not in _json.dumps(decision_log(decision, fallback_signals()))


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_4_runtime_logs_the_entry_count_of_the_asked_area(monkeypatch):
    from app.config import config
    from app.models import CounselorTurnDecision
    from app.pai_c.policy.classifier import fallback_signals
    from app.pai_c.policy.controller import Decision
    from sqlalchemy import select
    from tests.test_adaptive_counseling import _ask
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    asked = Decision(rule_id="explore_area", action="explore_area", topic="interests", question_allowed=True,
                     invite=False, summary_due=False)
    with StudentSession() as student:
        with patch("app.pai_c.policy.controller.decide", return_value=asked):
            await _ask(student, fallback_signals())
        with student.factory() as db:
            logged = db.scalar(select(CounselorTurnDecision)).decision
    assert logged["topic"] == "interests" and logged["topic_items"] == 0


# R2-5: a quote that differs from the student's text only in dash or quote marks is found.

def _budget(student_text, quote, value=None):
    import types
    from app.memory import extractor
    from app.memory.field_definitions import catalog_field_definitions
    keys = {spec["key"] for spec in catalog_field_definitions()}
    turn = types.SimpleNamespace(user_text=student_text, vault={}, vault_guesses=(), records=[], items=[],
                                 user_event_id="u", assistant_event_id="a", source_language="en")
    raw = {"candidate_type": "vault_fact", "operation": "upsert", "key": "finance.budget",
           "proposed_value": value or {"min": 1500000, "max": 2000000, "currency": "PKR", "period": "per_year"},
           "quote": quote, "confidence": 0.9}
    drops = []
    return extractor._validate(raw, turn, keys, drops), drops


@pytest.mark.req("R-47")
@pytest.mark.parametrize("student_text, quote", [
    ("Budget ka masla hai - my family can afford 15 to 20 lakh a year.", "Budget ka masla hai — my family can afford 15 to 20 lakh a year"),
    ("Budget ka masla hai — my family can afford 15 to 20 lakh a year.", "Budget ka masla hai - my family can afford 15 to 20 lakh a year"),
    ("We can pay 15-20 lakh per year.", "15–20 lakh per year"),
    ("We can pay 15–20 lakh per year.", "15-20 lakh per year"),
    ("My family’s limit is 15 to 20 lakh.", "My family's limit is 15 to 20 lakh"),
    ('Abbu said "15 to 20 lakh max".', "Abbu said “15 to 20 lakh max”"),
    ("Abbu said ‘15 to 20 lakh max’.", "Abbu said '15 to 20 lakh max'"),
])
def test_r2_5_budget_quote_matches_across_dash_and_quote_variants(student_text, quote):
    candidate, drops = _budget(student_text, quote)
    assert drops == []
    assert candidate is not None and candidate.key == "finance.budget"


@pytest.mark.req("R-47")
def test_r2_5_a_quote_the_student_never_wrote_is_still_dropped_with_a_reason_code(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="app.memory.extractor")
    candidate, drops = _budget("We can pay 15 lakh per year.", "We can pay 25 lakh per year")
    assert candidate is None
    assert [row["reason"] for row in drops] == ["quote not found in the student's message"]
    lines = [r.getMessage() for r in caplog.records if "memory_candidate_dropped" in r.getMessage()]
    assert lines == ["memory_candidate_dropped reason=quote_not_found candidate_type=vault_fact key=finance.budget"]
    assert "25 lakh" not in caplog.text and "15 lakh" not in caplog.text
