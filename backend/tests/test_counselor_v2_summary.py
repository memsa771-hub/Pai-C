from app.counseling.extraction import SlotClaim, TurnExtraction
from app.counseling.extraction import parse_extraction
from app.models import ProfileRequirement
import json
from app.counseling.slots import SlotState
from app.counseling.summary import has_correction, is_explicit_confirmation, summary_payload


def extraction(*claims):
    return TurnExtraction(tuple(claims), "", "none", "en", ())


def test_summary_only_uses_known_student_values():
    states = {
        "stated_goal": SlotState("stated_goal", "answered", {"title": "MS in power electronics", "id": "private"}),
        "budget": SlotState("budget", "pending", {"amount": 10, "currency": "PKR", "period": "year"}),
        "timing": SlotState("timing", "valid_unknown"),
        "family_wish": SlotState("family_wish", "missing"),
    }
    result = summary_payload(states)
    assert result == {
        "stated_goal": {"value": "MS in power electronics", "status": "answered"},
        "budget": {"value": {"amount": 10, "currency": "PKR", "period": "year"},
                   "status": "pending"},
        "timing": {"value": None, "status": "valid_unknown"},
    }


def test_correction_wins_over_confirmation_and_changes_draft():
    draft = {"status": "awaiting_confirmation", "summary": {
        "stated_goal": {"value": "MS in Germany", "status": "pending"},
    }}
    correction = TurnExtraction((SlotClaim("goal_summary_confirmed", "confirmed", .99, "yes"),
                                 SlotClaim("stated_goal", {"title": "MS in Pakistan"}, .9, "Pakistan")),
                                "", "none", "en", (), summary_response="corrected")
    assert is_explicit_confirmation(correction, draft)
    assert has_correction(correction, draft)
    revised = summary_payload({"stated_goal": SlotState("stated_goal", "answered", {"title": "MS in Germany"})},
                              correction)
    assert revised["stated_goal"] == {"value": "MS in Pakistan", "status": "pending"}


def test_no_confirmation_without_existing_draft_or_explicit_extraction():
    assert not is_explicit_confirmation(extraction(SlotClaim("goal_summary_confirmed", "confirmed", .9, "yes")), None)
    assert not is_explicit_confirmation(extraction(), {"status": "awaiting_confirmation"})


def test_rephrased_same_facts_do_not_count_as_correction():
    draft = {"status": "awaiting_confirmation", "summary": {
        "stated_goal": {"value": "MS in Germany", "status": "pending"}}}
    reply = TurnExtraction((SlotClaim("stated_goal", {"title": "master's in Germany"},
                                     .9, "master's in Germany"),),
                           "", "none", "en", (), summary_response="confirmed")
    assert is_explicit_confirmation(reply, draft)
    assert not has_correction(reply, draft)


def test_extractor_cannot_turn_a_correction_into_confirmation():
    row = ProfileRequirement(key="discovery.goal_summary_confirmed", stage="summary",
                             tier="important", source_type="journey_gap",
                             source_key="goal_summary_confirmed", selector="any",
                             question="Is that right?", version=1)
    raw = json.dumps({"slots": {"goal_summary_confirmed": {
        "value": "no", "confidence": 0.95, "quote": "No"
    }}, "student_question": "", "emotion": "none", "language": "en",
        "unknown_or_declined": []})
    assert parse_extraction(raw, "No, I meant later", [row]).claims == ()
