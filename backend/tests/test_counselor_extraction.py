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
                       "unknown_or_declined": list(unknown)}, ensure_ascii=False)


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


@pytest.mark.asyncio
async def test_one_aux_model_call_receives_same_context_without_channel():
    rows = [requirement("field_interest")]
    response = envelope({"field_interest": {"value": "biology", "confidence": 0.9,
                                             "quote": "biology"}}, language="roman_ur")
    with patch("app.counseling.extraction.chat_completion", new=AsyncMock(return_value=response)) as model:
        result = await extract_turn("biology pasand hai", [{"role": "user", "content": "hello"}],
                                    rows, {"city": "Lahore"})
    assert result.claims[0].value == "biology"
    model.assert_awaited_once()
    call = model.call_args.kwargs
    assert call["response_format"]["type"] == "json_schema"
    assert "channel" not in call["messages"][0]["content"]
    assert "Lahore" in call["messages"][0]["content"]


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
