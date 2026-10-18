"""Final policy cap preserves the chosen action and uses the existing Voice guard."""
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import config
from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.policy import classifier, controller
from app.pai_c.policy.state import derive_state
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn
from tests.test_policy_guided import state


@pytest.mark.parametrize("mode", ["guided", "strict"])
@pytest.mark.parametrize("action", [
    "care", "explore_correction", "mirror", "first_picture", "guide", "discover",
    "counsel", "adjust", "answer_request", "summarize", "ask", "ask_choice",
    "listen_reflect", "insight",
])
def test_final_cap_covers_every_action_without_replacing_it(monkeypatch, mode, action):
    load = controller.load_data
    table = copy.deepcopy(load(controller.TABLES[mode]))
    # Isolate the final check from selection, including future care questions.
    table["rows"] = [{"id": "selected", "when": True, "set": {
        "action": action, "question_allowed": True, "topic": "history", "invite": True}}]
    assert table["post_checks"][-1]["id"] == "question_cap"
    monkeypatch.setattr(controller, "load_data", lambda name:
        table if name == controller.TABLES[mode] else load(name))
    decision = controller.decide(state(questions_in_last_two=True), mode=mode)
    assert (decision.action, decision.topic, decision.invite) == (action, "history", True)
    assert decision.question_allowed is (action == "care")
    assert decision.rule_id == ("selected" if action == "care" else "selected+question_cap")


@pytest.mark.parametrize("mode,changes,action", [
    ("guided", {"first_picture_due": True}, "first_picture"),
    ("guided", {"intent": "deciding", "summary_confirmed": True}, "guide"),
    ("strict", {"intent": "deciding"}, "guide"),
    ("strict", {"intent": "asking_info", "request": {"needs_context": True}}, "answer_request"),
    ("strict", {"intent": "pushback"}, "adjust"),
])
def test_selected_action_survives_two_asking_replies(mode, changes, action):
    uncapped = controller.decide(state(**changes), mode=mode)
    capped = controller.decide(state(**changes, questions_in_last_two=True), mode=mode)
    assert uncapped.question_allowed and not capped.question_allowed
    assert capped.action == uncapped.action == action
    assert (capped.topic, capped.invite) == (uncapped.topic, uncapped.invite)
    assert capped.rule_id == uncapped.rule_id + "+question_cap"


def test_cap_runs_after_strict_no_repeat():
    result = controller.decide(state(
        intent="pushback", coverage={}, questions_in_last_two=True,
        previous={"action": "adjust", "topic": None}), mode="strict")
    assert result.action == "ask" and result.topic == "status"
    assert result.rule_id == "adjust+no_repeat+question_cap"
    assert not result.question_allowed


@pytest.mark.parametrize("replies,capped", [
    ([], False), (["One?"], False), (["One?", "A statement."], False),
    (["One?", "Two?"], True),
])
def test_cap_uses_actual_recent_reply_cadence(replies, capped):
    signals = classifier.fallback_signals().model_copy(update={"intent": "deciding"})
    inputs = derive_state(signals, coverage={}, mirror_ready=False, plan=None,
        student_count=10, prior_decisions=[], replies=replies, student_ordinals={},
        current_event_id="current", summary_confirmed=True)
    for mode in ("guided", "strict"):
        result = controller.decide(inputs, mode=mode)
        assert result.action == "guide" and result.question_allowed is not capped


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,action", [
    ("guided", "first_picture"), ("guided", "guide"), ("strict", "guide"),
])
async def test_reproductions_reach_voice_without_a_third_question(monkeypatch, mode, action):
    monkeypatch.setattr(config, "PAI_POLICY_MODE", mode)
    decision = controller.decide(state(
        first_picture_due=action == "first_picture", intent="deciding",
        summary_confirmed=action == "guide", questions_in_last_two=True), mode=mode)
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
    assert decision.action == action and not decision.question_allowed
    assert result.reply == text and "question_removed" in result.guard_violations
    assert model.await_count == 1
    prompt = model.await_args.kwargs["system_prompt"]
    block = json.loads(prompt.rsplit("<context>", 1)[1].split("<decision>", 1)[1].split("</decision>")[0])
    assert block["action"] == action and block["question_allowed"] is False


@pytest.mark.parametrize("mode", ["guided", "strict"])
def test_distress_keeps_care_priority_and_cap_is_inactive(monkeypatch, mode):
    result = controller.decide(state(
        safety={"level": "urgent"}, first_picture_due=True, intent="deciding",
        summary_confirmed=True, questions_in_last_two=True), mode=mode)
    assert result.action == "care" and result.rule_id == "care"


def test_first_picture_instruction_ends_with_an_invitation():
    decision = controller.decide(state(first_picture_due=True), mode="guided")
    instruction = controller.decision_context(decision, None, None)["instruction"]
    assert 'End with the invitation: "Tell me what feels right and what feels wrong."' in instruction
    assert "ask what feels right" not in instruction and "?" not in instruction
