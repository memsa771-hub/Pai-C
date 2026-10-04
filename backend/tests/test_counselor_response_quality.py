"""The student sees counseling prose while profile state stays internal."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.counseling.decision_sufficiency import (DecisionSufficiencyEvaluator,
                                                 guard_premature_verdict)
from app.counseling.evaluator import CounselingEvaluator
from app.counseling.policy import CounselingPolicy
from app.counseling.turn_contract import (needs_response_repair, parse_turn,
                                          repair_student_response)
from app.counseling.understanding import StudentUnderstandingBuilder
from app.memory.student_snapshot import StudentSnapshot


def _view(records=None, facts=None):
    snapshot = StudentSnapshot("student", facts or {}, records or {}, (), datetime.now(timezone.utc))
    return StudentUnderstandingBuilder().build("student", snapshot=snapshot)


def _policy(view, semantics=None, *, recent_question_focus=None):
    state = CounselingEvaluator().derive(
        message="", vault_context=view, journey=None,
        completion={"personalizedCounselingEligible": False},
        turn_semantics=semantics or {}, recent_question_focus=recent_question_focus)
    return CounselingPolicy().decide(state)


def test_high_school_discovery_builds_education_without_upload_gate():
    first = _policy(_view())
    assert first.move == "ASK" and first.focus == "current_level"
    view = _view({"education": [{"id": "school", "qualification_name": "high school",
                                 "canonical_level": "upper_secondary",
                                 "academic_status": "current"}]})
    next_turn = _policy(view)
    assert next_turn.move == "ASK" and next_turn.focus == "current_qualification"
    assert next_turn.max_questions == 1
    assert next_turn.move != "REQUEST_DOCUMENT"
    assert next_turn.move != "SHOW_MIRROR"


def test_student_requests_progress_instead_of_another_intake_question():
    view = _view({"education": [{"id": "school", "qualification_name": "A Levels",
                                 "canonical_level": "upper_secondary",
                                 "academic_status": "current"}]})
    policy = _policy(view, {"wants_progress": True})
    assert policy.move == "COUNSEL" and policy.max_questions == 0


def test_recent_education_question_is_not_repeated_before_reconciliation():
    view = _view({"education": [{"id": "school", "qualification_name": "high school",
                                 "canonical_level": "upper_secondary",
                                 "academic_status": "current"}]})
    policy = _policy(view, recent_question_focus="current_qualification")
    assert policy.move == "REFLECT" and policy.max_questions == 0


def test_university_request_uses_profile_evidence_without_mirror_approval():
    records = {
        "education": [{"id": "school", "qualification_name": "A Levels",
                       "canonical_level": "upper_secondary", "academic_status": "current"}],
        "student_voice_statement": [{"id": "cs", "voice_type": "interest",
                                     "direction": "Computer Science",
                                     "statement": "I am interested in Computer Science"}],
    }
    view = _view(records)
    intent = {"type": "university_shortlist", "candidates": ["Computer Science"],
              "destination_scope": "abroad"}
    suff = DecisionSufficiencyEvaluator().evaluate(
        view, "university_shortlist", decision_intent=intent)
    assert not suff.recommendation_ready
    assert "approximate or predicted grades" in suff.missing_evidence
    assert "confirm the current student mirror" not in suff.missing_evidence
    policy = _policy(view, {"decision_intent": intent})
    assert policy.move == "ASK" and policy.max_questions == 1
    assert policy.focus == "approximate or predicted grades"
    assert policy.move != "SHOW_MIRROR"
    fallback = guard_premature_verdict("Choose University X", suff.to_dict(),
                                      final_recommendation=True)
    assert "predicted grades" in fallback
    assert "mirror" not in fallback.casefold()


def test_internal_state_never_appears_as_chat_response():
    raw = ('I can help with universities.\n\nCurrent mirror (partial):\n'
           'education.current_level: high school\nCounselor_state: {"next_move":"ASK"}')
    visible, state = parse_turn(raw)
    assert needs_response_repair(visible)
    assert state == {}
    assert "mirror" not in visible.casefold()
    assert "counselor_state" not in visible.casefold()
    wrapped, state = parse_turn('{"response":"Fact upsert: education.current_level",'
                                '"counselor_state":{"student_understanding_delta":{}}}')
    assert needs_response_repair(wrapped)
    assert state["student_understanding_delta"]["facts"] == []


def test_unsafe_response_is_rewritten_as_short_natural_counseling():
    async def run():
        with patch("app.inference.client.chat_completion", new_callable=AsyncMock) as model:
            model.return_value = ("I can help narrow universities abroad for Computer Science. "
                                  "What are your predicted A Level grades?")
            reply = await repair_student_response(
                "Current mirror: evidence.quote", student_message="Suggest me a university",
                policy_prompt="move=ASK; focus=predicted grades")
            assert "mirror" not in reply.casefold()
            assert "What are your predicted" in reply
            assert model.await_args.kwargs["max_tokens"] == 1200
            assert model.await_args.kwargs["reasoning_effort"] == "low"
    asyncio.run(run())
