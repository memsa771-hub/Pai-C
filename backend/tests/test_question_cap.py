"""Question usefulness replaces cadence caps; the existing Voice guard remains."""
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.policy import classifier, controller
from app.pai_c.policy.state import derive_state
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn
from tests.test_policy_guided import state


@pytest.mark.parametrize("action", [
    "care", "explore_correction", "mirror", "first_picture", "guide", "discover",
    "counsel", "answer_request",
])
def test_usefulness_guard_covers_every_action_without_replacing_it(monkeypatch, action):
    load = controller.load_data
    table = copy.deepcopy(load("guided_table.json"))
    # Isolate the final check from selection, including future care questions.
    table["rows"] = [{"id": "selected", "when": True, "set": {
        "action": action, "question_allowed": True, "topic": "history", "invite": True}}]
    assert table["post_checks"][-1]["id"] == "useful_question"
    monkeypatch.setattr(controller, "load_data", lambda name:
        table if name == "guided_table.json" else load(name))
    decision = controller.decide(state(questions_in_last_two=True))
    assert (decision.action, decision.topic, decision.invite) == (action, "history", True)
    exempt = action in {"care", "answer_request", "first_picture", "explore_correction"}
    assert decision.question_allowed is exempt
    assert decision.rule_id == ("selected" if exempt else "selected+useful_question")


@pytest.mark.parametrize("changes,action", [
    ({"first_picture_due": True}, "first_picture"),
    ({"intent": "deciding", "summary_confirmed": True}, "guide"),
])
def test_selected_action_survives_two_asking_replies(changes, action):
    uncapped = controller.decide(state(**changes, question_needed=True))
    capped = controller.decide(state(**changes, question_needed=True, questions_in_last_two=True))
    assert uncapped.question_allowed and capped.question_allowed
    assert capped.action == uncapped.action == action
    assert (capped.topic, capped.invite) == (uncapped.topic, uncapped.invite)
    assert capped.rule_id == uncapped.rule_id


@pytest.mark.parametrize("replies,capped", [
    ([], False), (["One?"], False), (["One?", "A statement."], False),
    (["One?", "Two?"], True),
])
def test_cadence_is_observed_but_does_not_decide_necessity(replies, capped):
    signals = classifier.fallback_signals().model_copy(update={"intent": "deciding"})
    inputs = derive_state(signals, coverage={area: {"covered": True} for area in
        controller.load_data("areas_policy.json")["priority"]}, mirror_ready=False, plan=None,
        student_count=10, prior_decisions=[], replies=replies, student_ordinals={},
        current_event_id="current", summary_confirmed=True)
    result = controller.decide(inputs)
    assert inputs["questions_in_last_two"] is capped
    assert result.action == "guide" and not result.question_allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["first_picture", "guide"])
async def test_reproductions_reach_voice_without_a_third_question(monkeypatch, action):
    decision = controller.decide(state(
        first_picture_due=action == "first_picture", intent="deciding",
        summary_confirmed=action == "guide", questions_in_last_two=True))
    invitation = "Tell me what feels right and what feels wrong."
    text = "Your interests and what you have tried point in similar directions. " + invitation
    model = AsyncMock(return_value=json.dumps({"reply": text + " Which matters most?",
        "moves": ["reflect"], "action": {"type": "none"}}))
    history = [{"role": "assistant", "content": "What have you tried?"},
               {"role": "assistant", "content": "What was that like?"}]
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, text="Mujhe samajh aa rahi hai"),
                history=history, decision=decision)
    assert decision.action == action
    if action == "first_picture":
        assert decision.question_allowed and result.reply == text + " Which matters most?"
    else:
        assert not decision.question_allowed
        assert result.reply == text and "question_removed" in result.guard_violations
    assert model.await_count == 1
    prompt = model.await_args.kwargs["system_prompt"]
    block = json.loads(prompt.rsplit("<context>", 1)[1].split("<decision>", 1)[1].split("</decision>")[0])
    assert block["action"] == action and block["question_allowed"] is decision.question_allowed


def test_distress_keeps_care_priority_and_cap_is_inactive(monkeypatch):
    result = controller.decide(state(
        safety={"level": "urgent"}, first_picture_due=True, intent="deciding",
        summary_confirmed=True, questions_in_last_two=True))
    assert result.action == "care" and result.rule_id == "care"


def test_first_picture_instruction_ends_with_an_invitation():
    decision = controller.decide(state(first_picture_due=True))
    instruction = controller.decision_context(decision, None, None)["instruction"]
    assert 'End with the invitation: "Tell me what feels right and what feels wrong."' in instruction
    assert "ask what feels right" not in instruction and "?" not in instruction
