"""Guided policy mode: guardrail table, first picture and coverage depth (offline)."""
import pytest

from app.config import config
from app.pai_c.policy import classifier, controller
from app.pai_c.policy.state import derive_state, first_picture_due

AREAS = controller.load_data("areas_policy.json")["priority"]


def state(**changes):
    base = {**classifier.fallback_signals().model_dump(),
            "coverage": {area: {"covered": True} for area in AREAS},
            "student_count": 10, "mirror_allowed": False, "mirror_correction": False,
            "first_picture_due": False, "summary_confirmed": False, "discover_available": False,
            "possibility_id": None, "summary_due": False, "short_reply_streak": 0,
            "invite_pending": False, "insight_available": False, "questions_in_last_two": False, "previous": {}}
    return {**base, **changes}


@pytest.mark.parametrize("changes,rule,action,question", [
    ({"safety": {"level": "urgent"}, "mirror_allowed": True}, "care", "care", False),
    ({"mirror_correction": True, "mirror_allowed": True}, "mirror_changes", "explore_correction", True),
    ({"mirror_allowed": True, "first_picture_due": True}, "mirror", "mirror", False),
    ({"first_picture_due": True, "questions_in_last_two": True}, "first_picture+question_cap", "first_picture", False),
    ({"intent": "deciding", "summary_confirmed": True}, "guide", "guide", True),
    ({"discover_available": True, "possibility_id": "p1"}, "discover", "discover", True),
    ({"questions_in_last_two": True, "discover_available": True}, "rest", "counsel", False),
    ({"intent": "deciding"}, "counsel", "counsel", True),
    ({"intent": "asking_task", "request": {"needs_context": False}}, "answer", "answer_request", False),
    ({}, "counsel", "counsel", True),
])
def test_guided_rows_first_match(changes, rule, action, question):
    result = controller.decide(state(**changes), mode="guided")
    assert (result.rule_id, result.action, result.question_allowed) == (rule, action, question)


def test_guided_has_only_question_cap_and_mode_comes_from_config(monkeypatch):
    assert [check["id"] for check in controller.load_data("guided_table.json")["post_checks"]] == ["question_cap"]
    previous = controller.decide(state(), mode="guided").as_dict()
    assert controller.decide(state(previous=previous), mode="guided").rule_id == "counsel"
    monkeypatch.setattr(config, "PAI_POLICY_MODE", "strict")
    assert controller.decide(state()).rule_id == "default"
    monkeypatch.setattr(config, "PAI_POLICY_MODE", "guided")
    assert controller.decide(state()).rule_id == "counsel"


def test_policy_mode_is_validated(monkeypatch):
    monkeypatch.setattr(config, "PAI_POLICY_MODE", "other")
    with pytest.raises(RuntimeError, match="PAI_POLICY_MODE"):
        config.validate_startup()


def coverage(covered):
    return {area: {"covered": index < covered} for index, area in enumerate(AREAS)}


@pytest.mark.parametrize("kwargs,expected", [
    ({}, True),
    ({"student_count": 7}, False),
    ({"coverage": coverage(3)}, False),
    ({"coverage": {**coverage(5), "history": {"covered": False}}}, False),
    ({"coverage": {**coverage(5), "status": {"covered": False}}}, False),
    ({"summary_confirmed": True}, False),
    ({"prior_decisions": [{"event_id": "e1", "decision": {"action": "first_picture"}}]}, False),
    ({"prior_decisions": [{"event_id": "e1", "decision": {"action": "counsel"}}]}, True),
])
def test_first_picture_due_conditions_and_once_only(kwargs, expected):
    args = {"coverage": coverage(4), "student_count": 8, "prior_decisions": [], "summary_confirmed": False}
    assert first_picture_due(**{**args, **kwargs}) is expected


def test_derive_state_exposes_first_picture_and_confirmation():
    signals = classifier.fallback_signals()
    common = dict(coverage=coverage(5), mirror_ready=False, plan=None, student_count=9,
                  prior_decisions=[], replies=[], student_ordinals={}, current_event_id="e9")
    derived = derive_state(signals, **common)
    assert derived["first_picture_due"] and not derived["summary_confirmed"]
    derived = derive_state(signals, **common, summary_confirmed=True)
    assert not derived["first_picture_due"] and derived["summary_confirmed"]


def test_action_texts_for_guided_mode():
    counsel = controller.decide(state(), mode="guided")
    text = controller.decision_context(counsel, None, None)["instruction"]
    assert text.strip() == "Follow the counseling loop for this reply."
    picture = controller.decide(state(first_picture_due=True), mode="guided")
    text = controller.decision_context(picture, None, None)["instruction"]
    assert text.startswith("Share your first picture of them.") and "Tell me what feels right and what feels wrong." in text


def test_min_items_are_data():
    import json
    from app.pai_c.understanding.data import DATA_DIR
    areas = json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))
    assert {area: spec["min_items"] for area, spec in areas.items()} == {
        "status": 1, "history": 2, "interests": 2, "strengths": 1,
        "family_social": 2, "values": 1, "pressures": 1, "sure": 1, "goals": 1, "options": 1}
