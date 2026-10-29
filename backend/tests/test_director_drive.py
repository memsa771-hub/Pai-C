"""PAI drives the conversation (BETA_CONVERSATION_SPEC 2.2/2.3): intro, the
question bank with its asked ledger and one follow-up, and the drive rule
enforced after writing. Offline: fake model replies only."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.policy import classifier, controller
from app.pai_c.policy.state import derive_state
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn

BANK = controller.load_data("question_bank.json")
ORDER = [item["intent_key"] for item in BANK["items"]]
AREAS = controller.load_data("areas_policy.json")["priority"]


def signals(**changes):
    return classifier.Signals.model_validate({**classifier.fallback_signals().model_dump(), **changes})


def inputs(sig=None, *, prior=(), replies=(), vault_types=(), count=6, coverage=None, **extra):
    """derive_state as build_state calls it, plus the derived keys decide reads."""
    state = derive_state(sig or signals(), coverage=coverage if coverage is not None else
                         {area: {"covered": True} for area in AREAS},
                         mirror_ready=False, plan=None, student_count=count,
                         prior_decisions=[{"event_id": f"e{i}", "decision": d} for i, d in enumerate(prior)],
                         replies=list(replies), student_ordinals={}, current_event_id="now",
                         vault_types=set(vault_types))
    return {**state, "mirror_due": False, "first_picture_due": False, "discover_available": False,
            "possibility_id": None, "relevant_myth": None, **extra}


def asked(*keys):
    return [{"action": "bank_question", "bank_intent": key} for key in keys]


def test_bank_has_nine_ordered_items_with_copy():
    assert ORDER == ["about_you", "hobbies", "accomplishments", "extracurriculars", "obstacles",
                     "identity", "character", "values", "more"]
    for item in BANK["items"]:
        assert set(item) == {"id", "area", "vault_types", "intent_key", "prompt", "followup_prompt"}
        assert item["area"] in AREAS and item["prompt"].strip() and item["followup_prompt"].strip()


def test_first_exchange_is_the_intro_with_the_open_question():
    decision = controller.decide(inputs(signals(intent="greeting")))
    assert (decision.rule_id, decision.action, decision.bank_intent) == ("intro", "intro", "about_you")
    assert decision.question_allowed and decision.must_drive
    instruction = controller.decision_context(decision, signals(), None)["instruction"]
    assert BANK["items"][0]["prompt"] in instruction


def test_bank_order_and_no_repeat():
    # The opening already asked "tell me about yourself": the bank starts at hobbies.
    seen = []
    prior = []
    replies = ["Tell me about yourself?"]
    for _ in range(len(ORDER) - 1):
        decision = controller.decide(inputs(prior=prior, replies=replies))
        assert decision.action == "bank_question" and decision.question_allowed
        seen.append(decision.bank_intent)
        prior.append(controller.Decision.as_dict(decision))
        replies.append("Something?")
    assert seen == ORDER[1:]
    # Every item asked: the ledger never repeats one; the existing rows take over.
    assert controller.decide(inputs(prior=prior, replies=replies)).action == "counsel"


def test_bank_skips_filled_vault_types_and_a_just_covered_area():
    state = inputs(replies=["Hi?"], vault_types={"interest", "achievement"},
                   sig=signals(mentioned_areas=["history"]))
    # hobbies (interest) and accomplishments (achievement) are known; extracurriculars'
    # area was just covered; obstacles is sensitive before the fourth message... at 6 it is asked.
    assert state["next_bank_item"]["intent_key"] == "obstacles"
    early = inputs(replies=["Hi?"], vault_types={"interest", "achievement", "activity"}, count=2)
    assert early["next_bank_item"]["intent_key"] == "character"


def test_short_answer_gets_one_followup():
    prior = asked("hobbies")
    short = signals(intent="short_reply")
    decision = controller.decide(inputs(short, prior=prior, replies=["What do you enjoy?"]))
    assert (decision.action, decision.bank_intent, decision.bank_followup) == ("bank_question", "hobbies", True)
    item = controller.bank_item("hobbies")
    assert item["followup_prompt"] in controller.decision_context(decision, short, None)["instruction"]
    # A second short answer moves on: one follow-up at most.
    prior.append(decision.as_dict())
    again = controller.decide(inputs(short, prior=prior, replies=["What do you enjoy?", "Why?"]))
    assert again.bank_intent == "accomplishments" and not again.bank_followup


def test_two_asking_replies_do_not_block_the_bank():
    decision = controller.decide({**inputs(replies=["One?", "Two?"]), "questions_in_last_two": True})
    assert decision.action == "bank_question" and decision.question_allowed
    assert decision.rule_id == "bank_question"


@pytest.mark.parametrize("intent", ["stop", "pushback", "deciding"])
def test_bank_waits_when_the_student_stops_pushes_back_or_decides(intent):
    state = inputs(signals(intent=intent), replies=["Hi?"])
    assert state["next_bank_item"] is None and not state["intro_due"]


def test_care_never_drives_and_stop_does_not_drive():
    care = controller.decide(inputs(signals(safety={"level": "concern", "category": "acute_distress"})))
    assert care.action == "care" and not care.must_drive and care.next_step is None
    stop = controller.decide(inputs(signals(intent="stop"), replies=["Hi?"]))
    assert not stop.must_drive
    assert controller.decide(inputs(replies=["Hi?"])).must_drive


def test_next_step_follows_the_journey_phase():
    proposed = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "PROPOSED"})
    assert proposed.next_step["phase"] == "proposed" and "Roadmap" in proposed.next_step["text"]
    # A phase that asks: the bank question this reply carries.
    asking = controller.decide(inputs(replies=["Hi?"]))
    assert asking.next_step["key"] == "bank:hobbies"


def _reply(text, action=None):
    return json.dumps({"reply": text, "moves": ["give"], "action": action or {"type": "none"}})


@pytest.mark.asyncio
async def test_drive_guard_rewrites_once():
    decision = controller.decide(inputs(replies=["Hi?"]))
    model = AsyncMock(side_effect=[_reply("That sounds like a full week."),
                                   _reply("That sounds like a full week. What do you enjoy most in your free time?")])
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "I study and help at home."), history=[],
                                         decision=decision, signals=signals())
    assert result.reply.endswith("free time?") and "drive_retry" in result.guard_violations
    assert model.await_count == 2
    assert "did not end with a next step" in model.await_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_drive_guard_appends_the_phase_line_after_a_failed_rewrite():
    decision = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "PROPOSED"})
    model = AsyncMock(return_value=_reply("Those are good things to weigh."))
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "ok"), history=[],
                                         decision=decision, signals=signals())
    line = controller.load_data("next_steps.json")["phases"]["proposed"]["line"]
    assert result.reply == "Those are good things to weigh.\n\n" + line
    assert result.action == {"type": "show_place", "place": "roadmap"}
    assert {"drive_retry", "drive_appended"} <= set(result.guard_violations)


@pytest.mark.asyncio
async def test_drive_line_never_adds_a_second_question():
    decision = controller.decide(inputs(replies=["Hi?"]))
    model = AsyncMock(return_value=_reply("Why that? And what else do you like?"))
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "cricket"), history=[],
                                         decision=decision, signals=signals())
    assert result.reply.count("?") == 1 and model.await_count == 1


@pytest.mark.asyncio
async def test_care_reply_is_not_driven():
    decision = controller.decide(inputs(signals(safety={"level": "concern", "category": "acute_distress"})))
    model = AsyncMock(return_value=_reply("I'm here with you. You don't have to sort this out alone.",
                                          {"type": "wellbeing"}))
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "I can't take this anymore"), history=[],
                                         decision=decision, signals=signals(), instructions="wellbeing",
                                         safety_level="concern")
    assert result.reply.endswith("alone.") and model.await_count == 1
    assert "drive_appended" not in result.guard_violations


# ---- fix round 1 ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_page_name_mid_reply_is_not_a_next_step():
    decision = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "PROPOSED"})
    model = AsyncMock(return_value=_reply("Your Mirror shows you like robotics. That fits building things."))
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "ok"), history=[], decision=decision, signals=signals())
    assert model.await_count == 2 and {"drive_retry", "drive_appended"} <= set(result.guard_violations)
    assert result.reply.endswith(decision.next_step["text"])


@pytest.mark.asyncio
async def test_the_writers_next_step_field_is_the_last_line():
    decision = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "PROPOSED"})
    output = json.dumps({"reply": "Those two fields both use maths.", "next_step": "Open the Roadmap page and pick one.",
                         "moves": ["give"], "action": {"type": "none"}})
    model = AsyncMock(return_value=output)
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "ok"), history=[], decision=decision, signals=signals())
    assert result.reply == "Those two fields both use maths.\n\nOpen the Roadmap page and pick one."
    assert model.await_count == 1 and "drive_retry" not in result.guard_violations


@pytest.mark.asyncio
async def test_a_question_step_is_dropped_when_the_step_is_an_action():
    decision = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "PROPOSED"})
    output = json.dumps({"reply": "Those two fields both use maths.", "next_step": "Which one do you like?",
                         "moves": ["give"], "action": {"type": "none"}})
    model = AsyncMock(return_value=output)
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student, "ok"), history=[], decision=decision, signals=signals())
    assert "?" not in result.reply and result.reply.endswith(decision.next_step["text"])


@pytest.mark.asyncio
async def test_non_english_append_renders_the_step():
    from app.pai_c import language
    decision = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "PROPOSED"})
    model = AsyncMock(return_value=_reply("Dono fields mein maths hai."))
    render = AsyncMock(return_value=json.dumps({"text": "Roadmap page kholo aur ek field chuno."}))
    with StudentSession() as student, student.factory() as db:
        language.set_chat_language(db, student.workspace_id, {"code": "xx", "script": "latin"})
        db.commit()
        with patch("app.pai_c.deep.turn.chat_completion", model), patch("app.inference.gateway.complete", render):
            result = await run_deep_turn(db, _turn(student, "ok"), history=[], decision=decision, signals=signals())
    assert result.reply == "Dono fields mein maths hai.\n\nRoadmap page kholo aur ek field chuno."
    assert render.await_count == 1


def test_bank_interleaves_a_missing_education_basic_after_three_in_a_row():
    """A fresh student (no education basic known): 1-3 bank, 4 a basic, 5-7 bank."""
    assert BANK["bank_max_in_a_row"] == 3
    prior, replies, moves = [], [], []
    for count in range(1, 8):
        decision = controller.decide(inputs(prior=prior, replies=replies, count=count, coverage={}))
        moves.append(decision.action)
        prior.append(decision.as_dict())
        replies.append("Question?")
    assert moves == ["intro", "bank_question", "bank_question", "explore_area",
                     "bank_question", "bank_question", "bank_question"]
    assert prior[3]["topic"] in controller.load_data("areas_policy.json")["education_basics"]
    assert prior[3]["question_allowed"]


def test_answer_move_drives_with_the_next_bank_question_while_getting_to_know():
    ask = {"text": "What is software engineering?", "kind": "information", "needs_research": False,
           "needs_context": False}
    decision = controller.decide(inputs(signals(intent="asking_info", request=ask), replies=["Hi?"]))
    assert decision.action == "answer_request" and not decision.question_allowed
    assert decision.next_step["key"] == "bank:hobbies" and decision.next_step["question"]


def test_chosen_next_step_is_the_routes_first_open_step():
    from sqlalchemy import select
    from app.models import RouteDecision
    from app.pai_c.policy.state import route_next_step
    steps = [{"key": "group", "label_key": "step_any_group", "values": {}, "status": "done"},
             {"key": "test:ecat", "label_key": "step_test", "values": {"name": "ECAT"}, "status": "not"},
             {"key": "apply", "label_key": "step_apply", "values": {"degree": "BS Computer Science"}, "status": "not"}]
    with StudentSession() as student, student.factory() as db:
        assert route_next_step(db, student.workspace_id) is None
        db.add(RouteDecision(workspace_id=student.workspace_id, field_key="computer_science", title="Computer Science",
                             verdict={}, route={}, steps=steps, steps_done=[]))
        db.commit()
        assert route_next_step(db, student.workspace_id) == "Take ECAT"
        db.scalar(select(RouteDecision)).steps_done = ["test:ecat"]
        db.commit()
        assert route_next_step(db, student.workspace_id) == "Apply for BS Computer Science"
    chosen = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "CHOSEN", "route_step": "Take ECAT"})
    assert "Take ECAT" in chosen.next_step["text"]
    generic = controller.decide({**inputs(replies=["Hi?"]), "journey_stage": "CHOSEN"})
    assert generic.next_step["text"] == controller.load_data("next_steps.json")["phases"]["chosen"]["line"]
