"""PAI stays on education: prompt rules, area priority and question permission (offline)."""
from pathlib import Path

import pytest

from app.pai_c.deep.prompts import load_prompt
from app.pai_c.policy import controller
from tests.test_policy_guided import state

BACKEND = Path(__file__).resolve().parents[1]
ACTIONS = BACKEND / "app/pai_c/policy/actions"
BANNED = ("great question", "amazing", "achi misaalein", "zabardast", "shukriya")
BASICS = controller.load_data("areas_policy.json")["education_basics"]


def test_guided_prompt_puts_education_first_without_praise_or_echo():
    prompt = load_prompt("voice_guided")
    for line in (
        "PAI is an educational counselor. Every question serves choosing a field of study or a place to study it.",
        "No praise and no affirmations.",
        "Never repeat the student's words back as a summary unless they ask for one.",
        "end with ONE short question about the most relevant missing basic",
        "Never probe hobbies or side activities that do not help decide between fields.",
        "Answer a direct request first.",
    ):
        assert line in prompt
    texts = [prompt] + [path.read_text(encoding="utf-8") for path in ACTIONS.glob("*.md")]
    for text in texts:
        assert not any(word in text.lower() for word in BANNED)


def test_guided_prompt_is_documented_verbatim():
    docs = BACKEND.parent / "docs/counselor/COUNSELOR_V3_PROMPTS.md"
    if not docs.exists():
        pytest.skip("docs are not mounted")
    section = docs.read_text(encoding="utf-8").split("## 7.", 1)[1].split("\n## ", 1)[0]
    assert section.split("```text\n", 1)[1].split("\n```", 1)[0].rstrip() == load_prompt("voice_guided").rstrip()


def test_askable_areas_start_with_education_and_goals():
    policy = controller.load_data("areas_policy.json")
    assert policy["priority"][:5] == ["history", "goals", "options", "pressures", "interests"]
    assert policy["priority"][-2:] == ["values", "strengths"]
    early = controller.askable_areas(state(coverage={}, student_count=1))
    assert early[:3] == ["history", "goals", "options"]
    assert "values" not in early and "strengths" not in early
    assert "values" in controller.askable_areas(state(coverage={}, student_count=1, mentioned_areas=["values"]))
    assert "subjects" in policy["topic_text"]["interests"]
    assert "study" in policy["topic_text"]["family_social"]


@pytest.mark.parametrize("changes", [
    {"intent": "sharing"},
    {"intent": "sharing", "opened_thread": "interests", "mentioned_areas": ["interests"]},
])
def test_missing_education_basic_allows_one_question_even_when_classifier_says_no(changes):
    covered = {area: {"covered": area not in ("history", "goals")} for area in BASICS}
    decision = controller.decide(state(coverage=covered, question_needed=False, **changes))
    assert decision.question_allowed
    if "opened_thread" not in changes:
        assert (decision.action, decision.topic) == ("explore_area", "history")


def test_two_asking_replies_pause_only_the_basic_question():
    missing = {"history": {"covered": False}, **{area: {"covered": True} for area in BASICS[1:]}}
    assert not controller.decide(state(coverage=missing, question_needed=False,
        questions_in_last_two=True)).question_allowed
    assert controller.decide(state(coverage=missing, question_needed=True,
        questions_in_last_two=True)).question_allowed


def test_question_stays_off_for_care_and_when_basics_are_known():
    assert not controller.decide(state(coverage={}, safety={"level": "urgent"})).question_allowed
    hobby = controller.decide(state(question_needed=False, intent="sharing",
        opened_thread="interests", mentioned_areas=["interests"]))
    assert not hobby.question_allowed


def test_extractor_prompt_third_person_done_vs_planned_and_hobbies_as_evidence():
    prompt = (BACKEND / "app/memory/prompts/extractor.md").read_text(encoding="utf-8")
    for line in (
        "Write every value in the third person",
        'never "wants me"',
        "Something the student built or finished is done, never planned",
        "is Stated, not inferred",
        "Hobbies and side activities are captured only as supporting evidence",
        "mobility.relocation_willingness",
        "preferences.location_limits",
    ):
        assert line in prompt


def test_shared_voice_tail_has_no_affirm_move_and_hobbies_only_as_evidence():
    from app.pai_c.deep.turn import _parse_response
    for name in ("voice", "voice_guided"):
        prompt = load_prompt(name)
        assert '"affirm"' not in prompt and "Engage with these naturally" not in prompt
        assert "count only as supporting evidence when they help decide between fields" in prompt
    reply = '{"reply": "Theek hai.", "moves": ["affirm", "give"], "action": {"type": "none"}}'
    assert _parse_response(reply)[2] == ["give"]


def test_classifier_asks_when_an_education_basic_is_missing():
    prompt = (BACKEND / "app/pai_c/policy/prompts/turn_classifier.md").read_text(encoding="utf-8")
    assert "uncovered profile area alone is NOT a reason to ask" not in prompt
    assert "valid whole-person counseling context" not in prompt
    for line in ("an education basic is missing", "entry test plans", "the turn is not care"):
        assert line in prompt
    docs = BACKEND.parent / "docs/counselor/COUNSELOR_V3_PROMPTS.md"
    if docs.exists():
        section = docs.read_text(encoding="utf-8").split("## 8.", 1)[1].split("\n## ", 1)[0]
        assert section.split("```text\n", 1)[1].split("\n```", 1)[0].rstrip() == prompt.rstrip()
