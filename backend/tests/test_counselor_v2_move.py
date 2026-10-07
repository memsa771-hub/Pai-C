"""Move selection remains stable across chat and voice delivery."""

from types import SimpleNamespace

import pytest

from app.counseling.move import plan_move
from app.counseling.slots import SlotState


class Snapshot:
    records = {}

    def fact_value(self, key):
        return None


SLOTS = [SimpleNamespace(key="discovery.recent_qualification", stage="foundation",
                         priority=100, applicability={}, question_intent="Recent education"),
         SimpleNamespace(key="discovery.stated_goal", stage="direction",
                         priority=100, applicability={}, question_intent="Student goal")]
STATES = {"recent_qualification": SlotState("recent_qualification", "missing"),
          "stated_goal": SlotState("stated_goal", "missing")}


@pytest.mark.parametrize("scope,question,emotion,returning,confirmed,awaiting,stage,expected", [
    ("in_scope", "", "none", False, False, False, "FOUNDATION", "ask"),
    ("in_scope", "what is this?", "none", False, False, False, "FOUNDATION", "answer_then_ask"),
    ("in_scope", "", "disappointed", False, False, False, "FOUNDATION", "acknowledge_then_ask"),
    ("off_topic", "", "none", False, False, False, "FOUNDATION", "redirect_then_ask"),
    ("in_scope", "", "none", True, False, False, "FOUNDATION", "returning_student"),
    ("in_scope", "", "none", True, False, True, "DIRECTION", "ask"),
    ("in_scope", "", "none", True, True, True, "DIRECTION", "confirm_and_queue_research"),
    ("wellbeing", "", "none", False, False, False, "FOUNDATION", "wellbeing"),
    ("crisis", "", "none", False, False, False, "FOUNDATION", "crisis"),
    ("in_scope", "", "none", False, True, True, "DIRECTION", "confirm_and_queue_research"),
])
def test_move_precedence_identical_for_channels(scope, question, emotion, returning,
                                                confirmed, awaiting, stage, expected):
    results = []
    for _channel in ("chat", "voice"):
        results.append(plan_move(stage=stage, requirements=SLOTS, states=STATES,
                                 snapshot=Snapshot(), scope=scope,
                                 student_question=question, emotion=emotion,
                                 language="en", returning=returning,
                                 confirmed=confirmed, awaiting_confirmation=awaiting))
    assert results[0] == results[1]
    assert results[0].type == expected
    if expected in {"wellbeing", "crisis", "confirm_and_queue_research"}:
        assert results[0].slot_key is None


def test_completed_direction_summarizes_and_pending_foundation_skips():
    states = dict(STATES, stated_goal=SlotState("stated_goal", "pending", "MS"))
    move = plan_move(stage="DIRECTION", requirements=SLOTS, states=states,
                     snapshot=Snapshot(), scope="in_scope", student_question="",
                     emotion="none", language="roman_ur")
    assert move.type == "summarize_for_confirmation"
    assert move.max_words == 90
    assert move.language == "roman_ur"


def test_empty_first_turn_greets_but_volunteered_facts_do_not():
    kwargs = dict(stage="FOUNDATION", requirements=SLOTS, states=STATES,
                  snapshot=Snapshot(), scope="in_scope", student_question="",
                  emotion="none", language="en")
    assert plan_move(**kwargs, first_turn=True).type == "greet"
    assert plan_move(**kwargs, first_turn=False).type == "ask"


def test_returning_with_no_open_direction_slot_summarizes_once():
    states = dict(STATES, stated_goal=SlotState("stated_goal", "answered", "MS"))
    move = plan_move(stage="DIRECTION", requirements=SLOTS, states=states,
                     snapshot=Snapshot(), scope="in_scope", student_question="",
                     emotion="none", language="en", returning=True)
    assert move.type == "summarize_for_confirmation"
