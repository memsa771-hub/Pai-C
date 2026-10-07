"""Structured multilingual extraction and candidate-only persistence."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.counseling.extraction import SlotClaim, TurnExtraction, extract_turn, parse_extraction
from app.counseling.slot_capture import _record_proposals, capture_turn_slots
from app.memory.student_snapshot import StudentSnapshot, StudentSnapshotService
from app.models import EventRecord, MemoryCandidate, ProfileFieldResponse, ProfileRequirement
from scripts.counselor_eval_support import StudentSession


def requirement(key, *, accepts_unknown=True):
    return ProfileRequirement(key=f"discovery.{key}", stage="direction", tier="important",
                              source_type="vault_fact", source_key=key, selector="any",
                              question="?", question_intent=f"Find {key}", priority=50,
                              accepts_unknown=accepts_unknown, version=1)


def envelope(slots, *, language="en", unknown=(), question="", emotion="none"):
    return json.dumps({"slots": slots, "student_question": question,
                       "emotion": emotion, "language": language,
                       "unknown_or_declined": list(unknown),
                       "summary_response": "other"}, ensure_ascii=False)


@pytest.mark.parametrize("message,language,quote", [
    ("I want to study data science", "en", "data science"),
    ("میں ڈیٹا سائنس پڑھنا چاہتی ہوں", "ur", "ڈیٹا سائنس"),
    ("mujhe data science parhni hai", "roman_ur", "data science"),
])
def test_exact_quote_and_language_fixtures(message, language, quote):
    rows = [requirement("field_interest")]
    result = parse_extraction(envelope({"field_interest": {
        "value": "data science", "confidence": 0.9, "quote": quote,
    }}, language=language), message, rows)
    assert result.language == language
    assert result.claims == (SlotClaim("field_interest", "data science", 0.9, quote),)


def test_bilal_multi_slot_message_keeps_every_explicit_answer():
    message = ("BS electrical engineering done 2025, CGPA 3.4. IELTS 7.0. uploaded both. "
               "I want MS in Germany in power electronics for EV industry")
    rows = [requirement(key) for key in ("recent_qualification", "academic_result",
                                       "academic_status", "stated_goal", "envisioned_outcome")]
    slots = {
        "recent_qualification": {"value": json.dumps({"qualification_name": "BS electrical engineering"}),
                                 "confidence": 0.95, "quote": "BS electrical engineering"},
        "academic_result": {"value": json.dumps({"gpa": 3.4}),
                            "confidence": 0.92, "quote": "CGPA 3.4"},
        "academic_status": {"value": "completed", "confidence": 0.92, "quote": "done 2025"},
        "stated_goal": {"value": json.dumps({"goal_type": "education", "title": "MS in Germany in power electronics"}),
                        "confidence": 0.93, "quote": "MS in Germany in power electronics"},
        "envisioned_outcome": {"value": "EV industry", "confidence": 0.9, "quote": "EV industry"},
    }
    result = parse_extraction(envelope(slots), message, rows)
    assert {item.key for item in result.claims} == {row.key.removeprefix("discovery.") for row in rows}


def test_hamza_unknown_and_refused_budget_need_exact_evidence():
    rows = [requirement("stated_goal"), requirement("budget")]
    message = "honestly i dont know. don't want to say my budget"
    slots = {
        "stated_goal": {"value": "unknown", "confidence": 0.95, "quote": "i dont know"},
        "budget": {"value": "declined", "confidence": 0.9, "quote": "don't want to say my budget"},
    }
    result = parse_extraction(envelope(slots, unknown=("stated_goal", "budget")), message, rows)
    assert result.claims == ()
    assert result.unknown_or_declined == ("stated_goal", "budget")
    assert dict(result.response_statuses) == {"stated_goal": "valid_unknown", "budget": "declined"}
    slots["budget"]["quote"] = "not in the message"
    result = parse_extraction(envelope(slots, unknown=("budget",)), message, rows)
    assert result.unknown_or_declined == ()


def test_low_confidence_and_missing_quote_cannot_answer_slot():
    rows = [requirement("budget")]
    message = "Maybe 15 lakh a year"
    for confidence, quote in ((0.59, "15 lakh"), (0.9, "20 lakh")):
        result = parse_extraction(envelope({"budget": {
            "value": "1500000", "confidence": confidence, "quote": quote,
        }}), message, rows)
        assert result.claims == ()


def test_punctuation_normalized_quote_keeps_verbatim_student_evidence():
    rows = [requirement("qualification_group")]
    result = parse_extraction(envelope({"qualification_group": {
        "value": "Pre-Engineering", "confidence": .9,
        "quote": "pre-engineering",
    }}), "I studied pre engineering", rows)
    assert result.claims[0].quote == "pre engineering"


def test_typed_result_and_scalar_wrapper_reach_canonical_candidate_shape():
    rows = [requirement("academic_result"), requirement("academic_status")]
    message = "I finished FSc with 844/1100"
    slots = {
        "academic_result": {"value": {"marks_obtained": 844, "marks_total": 1100,
                                      "gpa": None, "gpa_scale": None,
                                      "percentage": None, "grade": None},
                            "confidence": 0.9, "quote": "844/1100"},
        "academic_status": {"value": {"value": "completed"},
                            "confidence": 0.9, "quote": "finished"},
    }
    result = parse_extraction(envelope(slots), message, rows)
    assert {claim.key: claim.value for claim in result.claims} == {
        "academic_result": {"marks_obtained": 844, "marks_total": 1100},
        "academic_status": "completed",
    }


def test_graduation_year_is_not_a_target_intake():
    message = "BS electrical engineering done 2025. I want MS in Germany"
    rows = [requirement("recent_qualification"), requirement("stated_goal"),
            requirement("timing")]
    slots = {
        "recent_qualification": {"value": {"qualification_name": "BS electrical engineering"},
                                 "confidence": .9, "quote": "BS electrical engineering done 2025"},
        "stated_goal": {"value": {"title": "MS in Germany", "goal_type": "education"},
                        "confidence": .9, "quote": "MS in Germany"},
        "timing": {"value": "2025", "confidence": .9, "quote": "2025"},
    }
    result = parse_extraction(envelope(slots), message, rows)
    assert "timing" not in {claim.key for claim in result.claims}


def test_spoken_completion_fragment_is_not_goal_timing():
    message = "I'm just completed it 2020... 2"
    rows = [requirement("academic_status"), requirement("timing")]
    result = parse_extraction(envelope({
        "academic_status": {"value": "completed", "confidence": .9,
                            "quote": message},
        "timing": {"value": "2020", "confidence": .9, "quote": "2020"},
    }), message, rows, expected_slot="recent_qualification")
    assert {claim.key for claim in result.claims} == {"academic_status"}


def test_bare_year_during_foundation_cannot_become_target_intake():
    message = "I'm just completed it 2020... 2"
    rows = [requirement("academic_result"), requirement("timing")]
    result = parse_extraction(envelope({
        "academic_result": None,
        "timing": {"value": "2020", "confidence": .9, "quote": "2020"},
    }), message, rows, expected_slot="academic_result")
    assert result.claims == ()


def test_spoken_year_fragment_cannot_become_gpa_or_marks():
    message = "I'm just completed it 2020... 2"
    rows = [requirement("academic_result")]
    for value in ({"gpa": 2}, {"marks_obtained": 2}, {"grade": "2020"}):
        result = parse_extraction(envelope({"academic_result": {
            "value": value, "confidence": .9, "quote": message,
        }}), message, rows, expected_slot="academic_result")
        assert result.claims == ()


def test_qualification_name_cannot_become_an_academic_grade():
    message = "fsc pre engineering was my highest qualification"
    rows = [requirement("recent_qualification"), requirement("academic_result")]
    result = parse_extraction(envelope({
        "recent_qualification": {"value": {"qualification_name": "fsc pre engineering"},
                                 "confidence": .9, "quote": "fsc pre engineering"},
        "academic_result": {"value": {"grade": "fsc pre engineering"},
                            "confidence": .9, "quote": "fsc pre engineering"},
    }), message, rows)
    assert {claim.key for claim in result.claims} == {"recent_qualification"}


def test_timing_claim_survives_null_other_slots():
    message = "I want to start next year"
    rows = [requirement("recent_qualification"), requirement("envisioned_outcome"),
            requirement("timing")]
    result = parse_extraction(envelope({"recent_qualification": None,
                                        "envisioned_outcome": None,
                                        "timing": {"value": "next year", "confidence": .9,
                                                   "quote": "next year"}}),
                              message, rows)
    assert result.claims[0].key == "timing"


def test_direct_answer_survives_omitted_general_slot():
    rows = [requirement("goal_reason")]
    message = "i like solving puzzles and helping diagnose people"
    item = {"value": message, "confidence": .9, "quote": message,
            "attribution": {"claim_owner": "student", "student_clause_quote": None,
                            "alignment_quote": None}}
    raw = json.dumps({"slots": {"goal_reason": None},
                      "answer_to_last_question": item,
                      "student_question": "", "emotion": "none", "language": "en",
                      "unknown_or_declined": []})
    result = parse_extraction(raw, message, rows, expected_slot="goal_reason")
    assert result.claims[0].key == "goal_reason"
    assert result.claims[0].attribution["claim_owner"] == "student"


def test_undecided_answer_to_goal_question_is_valid_unknown():
    rows = [requirement("stated_goal")]
    raw = json.dumps({"slots": {"stated_goal": None},
                      "answer_to_last_question": None,
                      "last_question_status": "unknown",
                      "student_question": "", "emotion": "stressed", "language": "en",
                      "unknown_or_declined": [], "summary_response": "other"})
    result = parse_extraction(raw, "i'm feeling stuck and don't know what to do",
                              rows, expected_slot="stated_goal")
    assert result.unknown_or_declined == ("stated_goal",)
    assert result.response_statuses == (("stated_goal", "valid_unknown"),)


def test_exact_last_answer_excerpt_fills_scalar_timing_only():
    rows = [requirement("timing")]
    message = "Main 2026 ke fall intake se shuru karna chahta hun"
    raw = json.dumps({"slots": {"timing": None}, "answer_to_last_question": None,
                      "answer_text": "2026 ke fall intake",
                      "last_question_status": "answered", "student_question": "",
                      "emotion": "none", "language": "roman_ur",
                      "unknown_or_declined": [], "summary_response": "other"})
    result = parse_extraction(raw, message, rows, expected_slot="timing")
    assert result.claims[0].value == "2026 ke fall intake"
    assert result.claims[0].quote in message


def test_record_patch_targets_matching_qualification_and_family_stays_separate():
    snapshot = StudentSnapshot("student", {}, {
        "education": [
            {"id": "old", "qualification_name": "FSc Pre-Medical"},
            {"id": "current", "qualification_name": "BS Computer Science"},
        ], "goal": [],
    }, (), datetime.now(timezone.utc))
    claims = {
        "recent_qualification": SlotClaim("recent_qualification", "BS Computer Science", 0.9, "BS Computer Science"),
        "academic_result": SlotClaim("academic_result", {"gpa": 3.2}, 0.9, "CGPA 3.2"),
        "family_wish": SlotClaim("family_wish", {
            "influencer_type": "parent", "source_label": "father",
            "suggested_direction": "engineering", "influence_type": "career_suggestion",
        }, 0.9, "father wants engineering"),
    }
    proposals = _record_proposals(claims, snapshot)
    assert proposals[0][0] == "education" and proposals[0][3] == "current"
    assert proposals[1][0] == "external_influence" and proposals[1][3] is None
    assert all(kind != "goal" for kind, *_ in proposals)
    claims["academic_result"] = SlotClaim("academic_result", {"gpa": 9.0}, 0.9, "CGPA 3.2")
    proposals = _record_proposals(claims, snapshot)
    assert "result" not in proposals[0][1]
    assert "academic_result" not in proposals[0][2]


def test_goal_reason_has_durable_student_voice_candidate_with_multiple_goals():
    snapshot = StudentSnapshot("student", {}, {
        "goal": [{"id": "old", "title": "MBBS"},
                 {"id": "new", "title": "explore lab work"}],
    }, (), datetime.now(timezone.utc))
    proposals = _record_proposals({
        "goal_reason": SlotClaim("goal_reason", "I like practical lab work", .9,
                                 "I like practical lab work")}, snapshot)
    assert any(kind == "student_voice_statement" and values == {
        "voice_type": "motivation", "statement": "I like practical lab work",
    } for kind, values, _, _ in proposals)


@pytest.mark.asyncio
async def test_one_aux_model_call_receives_same_context_without_channel():
    rows = [requirement("field_interest")]
    response = envelope({"field_interest": {"value": "biology", "confidence": 0.9,
                                             "quote": "biology"}}, language="roman_ur")
    with patch("app.counseling.extraction.chat_completion", new=AsyncMock(return_value=response)) as model:
        result = await extract_turn("biology pasand hai", [{"role": "user", "content": "hello"}],
                                    rows, {"city": "Lahore"}, expected_slot="field_interest")
    assert result.claims[0].value == "biology"
    model.assert_awaited_once()
    call = model.call_args.kwargs
    assert call["response_format"]["type"] == "json_schema"
    assert "channel" not in call["messages"][0]["content"]
    assert "Lahore" in call["messages"][0]["content"]
    assert "field_interest" in call["system_prompt"]


@pytest.mark.asyncio
async def test_focused_recovery_captures_missed_spoken_qualification():
    message = "I studied the FSc... Uh, n- pre- engineering"
    rows = [requirement("recent_qualification", accepts_unknown=False)]
    primary = envelope({"recent_qualification": None})
    focused = envelope({"recent_qualification": {
        "value": {"qualification_name": "FSc Pre-Engineering"},
        "confidence": .9, "quote": "I studied the FSc... Uh, n- pre- engineering",
    }})
    with patch("app.counseling.extraction.chat_completion",
               new=AsyncMock(side_effect=[primary, focused])) as model:
        result = await extract_turn(message, [], rows, {}, expected_slot="recent_qualification")
    assert model.await_count == 2
    assert result.claims == (SlotClaim("recent_qualification",
                                       {"qualification_name": "FSc Pre-Engineering"},
                                       .9, message),)


@pytest.mark.asyncio
async def test_empty_structured_response_retries_once_with_larger_limit():
    rows = [requirement("field_interest")]
    valid = envelope({"field_interest": {"value": "biology", "confidence": .9,
                                         "quote": "biology"}})
    with patch("app.counseling.extraction.chat_completion",
               new=AsyncMock(side_effect=["", valid])) as model:
        result = await extract_turn("biology", [], rows, {})
    assert result.claims[0].value == "biology"
    assert [call.kwargs["max_tokens"] for call in model.await_args_list] == [1200, 2400]


def test_capture_routes_student_claims_through_candidates_and_reconciler():
    with StudentSession() as student:
        event_id = "turn-extraction-test"
        with student.factory() as db:
            db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                               type="workspace.message.posted", source=f"human:{student.user_id}",
                               target="channel/pai-counselor", payload={"content": "BS CS completed"},
                               timestamp=student.next_timestamp()))
            db.commit()
            snapshot = StudentSnapshotService(db).build(student.workspace_id)
            rows = [requirement("recent_qualification"), requirement("academic_status"),
                    requirement("budget")]
            extracted = TurnExtraction(
                claims=(SlotClaim("recent_qualification", "BS CS", 0.95, "BS CS"),
                        SlotClaim("academic_status", "completed", 0.9, "completed")),
                student_question="", emotion="none", language="en",
                unknown_or_declined=("budget",),
                response_statuses=(("budget", "declined"),),
            )
            ids = capture_turn_slots(db, student.workspace_id, event_id, extracted,
                                     rows, snapshot, channel="voice")
            db.commit()
            assert len(ids) == 1
            candidate = db.get(MemoryCandidate, ids[0])
            assert candidate.candidate_type == "student_record"
            assert candidate.key == "education"
            assert candidate.input_channel == "voice"
            assert candidate.source_type == "conversation"
            assert candidate.status == "accepted"
            assert db.execute(select(ProfileFieldResponse).where(
                ProfileFieldResponse.workspace_id == student.workspace_id,
                ProfileFieldResponse.requirement_key == "discovery.budget",
            )).scalar_one().status == "declined"
            assert capture_turn_slots(db, student.workspace_id, event_id, extracted,
                                      rows, snapshot, channel="voice") == []
