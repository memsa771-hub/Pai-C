from types import SimpleNamespace

import pytest

from app.counseling.guard_v2 import approve_reply, deterministic_violations, fallback_reply
from app.counseling.move import CounselorMove
from app.counseling.slots import SlotState


SLOT = SimpleNamespace(key="discovery.budget", canonical_questions={
    "en": "Roughly how much can you spend?",
    "ur": "آپ کتنا خرچ کر سکتے ہیں؟",
    "roman_ur": "Aap kitna kharch kar sakte hain?",
    "mixed": "Aap kitna kharch kar sakte hain?",
}, question_intent="Find affordable budget and currency")


def move(**changes):
    data = dict(type="ask", slot_key="budget", question_intent="Find budget",
                reflect=(), answer_scope=None, language="en", max_words=60,
                stage="DIRECTION")
    data.update(changes)
    return CounselorMove(**data)


@pytest.mark.parametrize("reply,change,states,expected", [
    ("What is your budget? When?", {}, {}, "more_than_one_question"),
    ("What is your budget? Tell me soon.", {}, {}, "question_not_last"),
    ("Great, what is your budget?", {}, {}, "praise_or_filler_opener"),
    ("- First choice\n- Second choice\nWhat is your budget?", {}, {}, "unrequested_list"),
    ("Please tell me something. What is your budget?", {"max_words": 3}, {}, "word_limit"),
    ("What is your budget?", {}, {"budget": SlotState("budget", "pending", 100)}, "answered_slot_question"),
    ("I hear you.", {}, {}, "missing_planned_question"),
    ("What is your budget?", {"language": "ur"}, {}, "language_mismatch"),
    ("Which universities do you prefer?", {}, {}, "wrong_slot_question"),
    ("The word limit was declined by the system. What is your budget?", {}, {}, "internal_language"),
    ("Your budget is student_budget_words. What is your budget?", {}, {}, "internal_language"),
])
def test_deterministic_rules(reply, change, states, expected):
    assert expected in deterministic_violations(reply, move(**change), states, [SLOT])


@pytest.mark.asyncio
async def test_guard_rewrites_once_and_falls_back(monkeypatch):
    async def check(*args, **kwargs):
        return ("verdict",)
    monkeypatch.setattr("app.counseling.guard_v2.model_violations", check)
    calls = []

    async def writer(**kwargs):
        calls.append(kwargs["violations"])
        return "Great, this is guaranteed. What is your budget?"

    approved, violations = await approve_reply(
        reply="Great, this is guaranteed. What is your budget?",
        move=move(), student_text="I need advice", states={}, requirements=[SLOT],
        writer=writer, history=[], understanding={},
    )
    assert len(calls) == 1
    assert "verdict" in calls[0]
    assert approved == fallback_reply(move(), [SLOT])
    assert "guaranteed" not in approved
    assert violations
