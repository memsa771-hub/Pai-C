"""A student can ask how PAI works and get a true answer from data
(BETA_CONVERSATION_SPEC 2.4). Offline: fake classifier and Writer."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import BackgroundJob, CounselorNotedQuestion, CounselorTurnDecision, EventRecord
from app.pai_c.deep.grounding import allowed_context, guard_reply
from app.pai_c.policy import classifier, controller
from scripts.counselor_eval_support import StudentSession
from tests.test_director_drive import inputs, signals

ASK = {"text": "PAI kaise kaam karta hai?", "kind": "about_pai", "needs_research": False, "needs_context": False}


def test_about_pai_data_covers_the_four_features_and_limits():
    data = controller.load_data("about_pai.json")
    assert set(data["features"]) == {"Vault", "Mirror", "Paths", "Roadmap"}
    for key in ("what_pai_is", "your_words", "how_paths_are_made"):
        assert data[key].strip()
    assert len(data["will_not_do"]) == 3


def test_about_pai_row_comes_before_answer():
    decision = controller.decide(inputs(signals(intent="asking_info", request=ASK), replies=["Hi?"]))
    assert (decision.rule_id, decision.action, decision.topic) == ("about_pai", "about_pai", "request")
    assert decision.must_drive
    assert classifier.Request.model_validate(ASK).kind == "about_pai"


def test_about_pai_section_is_an_allowed_grounding_source():
    context = '<context><about_pai>{"x":"98% of answers are checked"}</about_pai></context>'
    reply, violations = guard_reply("About 98% of answers are checked.", "{}", (), allowed_context(context))
    assert violations == [] and "98%" in reply
    reply, violations = guard_reply("About 98% of answers are checked.", "{}", (), "")
    assert "ungrounded_world_number" in violations


@pytest.mark.asyncio
async def test_about_pai_is_answered_from_data_without_research_or_a_noted_question(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = signals(intent="asking_info", request=ASK, language={"code": "ur", "script": "latin"})
    prompts = []

    async def writer(**kwargs):
        prompts.append(kwargs["system_prompt"])
        return json.dumps({"reply": "PAI tumhara education counselor hai. Profile page par tumhara Vault hai.",
                           "moves": ["give"], "action": {"type": "show_place", "place": "profile"}})

    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", writer):
            await student.turn(ASK["text"])
        with student.factory() as db:
            decision = db.scalar(select(CounselorTurnDecision)).decision
            assert decision["action"] == "about_pai"
            assert db.scalar(select(CounselorNotedQuestion.id)) is None
            assert db.scalar(select(BackgroundJob.id).where(BackgroundJob.job_type == "research.claim")) is None
            posted = db.scalars(select(EventRecord).where(EventRecord.source == "openagents:pai",
                                                          EventRecord.type == "workspace.message.posted")).all()
            assert posted[-1].metadata_.get("workspace_place") == "profile"
    assert "<about_pai>" in prompts[0] and "_note" not in prompts[0].split("<about_pai>", 1)[1][:40]
    assert "Vault" in prompts[0].split("<about_pai>", 1)[1].split("</about_pai>", 1)[0]


@pytest.mark.asyncio
async def test_about_pai_section_only_for_that_move():
    from app.pai_c.deep.context import build_context
    from tests.test_counselor_deep_pr3 import _turn
    with StudentSession() as student, student.factory() as db:
        other = controller.decide(inputs(replies=["Hi?"]))
        context = await build_context(db, student.workspace_id, _turn(student), decision=other, signals=signals())
        assert "<about_pai>" not in context.text
