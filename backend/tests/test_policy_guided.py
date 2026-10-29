"""Guided policy mode: guardrail table, first picture and coverage depth (offline)."""
import pytest

from app.pai_c.policy import classifier, controller
from app.pai_c.policy.state import derive_state, first_picture_due

AREAS = controller.load_data("areas_policy.json")["priority"]


def state(**changes):
    base = {**classifier.fallback_signals().model_dump(),
            "coverage": {area: {"covered": True} for area in AREAS},
            "student_count": 10, "mirror_due": False,
            "first_picture_due": False, "discover_available": False,
            "possibility_id": None, "summary_due": False, "short_reply_streak": 0,
            "invite_pending": False, "insight_available": False, "questions_in_last_two": False, "previous": {}}
    return {**base, **changes}


@pytest.mark.parametrize("changes,rule,action,question", [
    ({"safety": {"level": "urgent"}, "mirror_due": True}, "care", "care", False),
    ({"mirror_due": True, "first_picture_due": True}, "mirror", "mirror", False),
    ({"first_picture_due": True, "questions_in_last_two": True}, "first_picture", "first_picture", True),
    ({"intent": "deciding", "mirror_ready": True}, "guide", "guide", False),
    ({"discover_available": True, "possibility_id": "p1"}, "discover", "discover", False),
    ({"questions_in_last_two": True, "discover_available": True}, "discover", "discover", False),
    ({"intent": "deciding"}, "guide", "guide", False),
    ({"intent": "asking_task", "request": {"needs_context": False}}, "answer", "answer_request", False),
    ({}, "counsel", "counsel", False),
])
def test_guided_rows_first_match(changes, rule, action, question):
    result = controller.decide(state(**changes))
    assert (result.rule_id, result.action, result.question_allowed) == (rule, action, question)


def test_guided_has_usefulness_guard():
    assert [check["id"] for check in controller.load_data("guided_table.json")["post_checks"]] == ["useful_question"]
    previous = controller.decide(state()).as_dict()
    assert controller.decide(state(previous=previous)).rule_id == "counsel"


# First-picture rules name status and history; this order keeps them first, independent of question priority.
COVERAGE_ORDER = ["status", "history", *[area for area in AREAS if area not in ("status", "history")]]


def coverage(covered):
    return {area: {"covered": index < covered} for index, area in enumerate(COVERAGE_ORDER)}


@pytest.mark.parametrize("kwargs,expected", [
    ({}, True),
    ({"student_count": 2}, True),
    ({"coverage": coverage(3)}, False),
    ({"coverage": {**coverage(5), "history": {"covered": False}}}, False),
    ({"coverage": {**coverage(5), "status": {"covered": False}}}, False),
    ({"mirror_ready": True}, False),
    ({"coverage": {**coverage(5), "history": {"covered": True, "stale": True}}}, False),
    ({"prior_decisions": [{"event_id": "e1", "decision": {"action": "first_picture"}}]}, False),
    ({"prior_decisions": [{"event_id": "e1", "decision": {"action": "counsel"}}]}, True),
])
def test_first_picture_due_conditions_and_once_only(kwargs, expected):
    args = {"coverage": coverage(4), "student_count": 8, "prior_decisions": [], "mirror_ready": False}
    assert first_picture_due(**{**args, **kwargs}) is expected


def test_derive_state_exposes_first_picture_until_the_mirror_is_ready():
    signals = classifier.fallback_signals()
    common = dict(coverage=coverage(5), plan=None, student_count=9,
                  prior_decisions=[], replies=[], student_ordinals={}, current_event_id="e9")
    derived = derive_state(signals, mirror_ready=False, **common)
    assert derived["first_picture_due"] and not derived["mirror_ready"]
    derived = derive_state(signals, mirror_ready=True, **common)
    assert not derived["first_picture_due"] and derived["mirror_ready"]


def test_action_texts_for_guided_mode():
    counsel = controller.decide(state())
    text = controller.decision_context(counsel, None, None)["instruction"]
    assert text.strip() == "Follow the counseling loop for this reply."
    picture = controller.decide(state(first_picture_due=True))
    text = controller.decision_context(picture, None, None)["instruction"]
    assert text.startswith("Share your first picture of them.") and "Tell me what feels right and what feels wrong." in text


def test_min_items_are_data():
    import json
    from app.pai_c.understanding.data import load_areas
    areas = load_areas()
    assert {area: spec["min_items"] for area, spec in areas.items()} == {
        "status": 1, "history": 2, "interests": 2, "strengths": 1,
        "family_social": 2, "values": 1, "pressures": 1, "sure": 1, "goals": 1, "options": 1}
