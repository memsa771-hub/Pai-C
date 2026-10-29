"""Golden conversations (BETA_CONVERSATION_SPEC 2): scripted student turns run
through the real runtime (classifier -> Director -> Writer guards -> post ->
extraction -> reconcile) with fake model providers. Each fixture names the
classifier output, the Writer's reply and the extractor's candidates per
turn; the test checks the moves, the Vault, the drive rule, one question per
reply, no praise, the chat language and about_pai. Fake replies show routing
and guards, not model quality."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.memory import extractor
from app.memory.vault_items import VaultItemService
from app.memory.student_records import StudentRecordService
from app.models import CounselorTurnDecision, Workspace
from app.pai_c.deep.polish import question_count
from app.pai_c.policy import classifier, controller
from scripts.counselor_eval_support import StudentSession

FIXTURES = Path(__file__).parent / "fixtures" / "conversations"
CASES = sorted(path.stem for path in FIXTURES.glob("*.json"))
BANNED = [*controller.load_data("mirror.json")["text"]["praise_words"], "great question", "shukriya"]
MARKERS = [marker.casefold() for phase in controller.load_data("next_steps.json")["phases"].values()
           for marker in phase["markers"]]


def _signals(changes):
    return classifier.Signals.model_validate({**classifier.fallback_signals().model_dump(), **changes})


def _writer_output(entry):
    reply = entry if isinstance(entry, dict) else {"reply": entry}
    return json.dumps({"moves": ["give"], "action": {"type": "none"}, **reply})


def test_the_five_golden_conversations_exist():
    assert CASES == ["asks_about_pai", "distressed", "english_student", "fresh_roman_urdu", "short_answers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", CASES)
async def test_golden_conversation(monkeypatch, name):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    case = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    current = {"turn": None, "writes": 0}
    prompts = []

    async def fake_classifier(**kwargs):
        return _signals(current["turn"]["signals"]).model_dump_json()

    async def fake_writer(**kwargs):
        prompts.append(kwargs["system_prompt"])
        script = current["turn"]["writer"]
        current["writes"] += 1
        return _writer_output(script[min(current["writes"], len(script)) - 1])

    async def fake_extractor(**kwargs):
        assert current["turn"]["student"] in kwargs["messages"][0]["content"]
        return json.dumps({"candidates": current["turn"]["extract"]})

    async def no_render(*args, **kwargs):
        raise AssertionError("a scripted reply that drives never needs rendered copy")

    with StudentSession() as student, \
            patch("app.pai_c.policy.classifier.complete", fake_classifier), \
            patch("app.pai_c.deep.turn.chat_completion", fake_writer), \
            patch.object(extractor, "chat_completion", fake_extractor), \
            patch.object(extractor, "_model_config", return_value=("test", "test", None)), \
            patch("app.inference.gateway.complete", no_render):
        for index, turn in enumerate(case["turns"]):
            current.update(turn=turn, writes=0)
            prompts.clear()
            await student.turn(turn["student"])
            await student.extract_and_reconcile()
            reply = student.transcript[-1]["content"]
            expect = turn["expect"]
            with student.factory() as db:
                rows = db.scalars(select(CounselorTurnDecision).where(
                    CounselorTurnDecision.workspace_id == student.workspace_id)
                    .order_by(CounselorTurnDecision.source_timestamp)).all()
                decision = rows[-1].decision
                language = db.get(Workspace, student.workspace_id).chat_language
            label = f"{name} turn {index + 1}"
            assert len(rows) == index + 1, label
            assert decision["action"] == expect["action"], label
            for key in ("bank_intent", "bank_followup"):
                if key in expect:
                    assert decision[key] == expect[key], label
            # The Writer's reply is posted as scripted: the guards did not need to rewrite it.
            assert current["writes"] == 1, label
            assert question_count(reply) <= 1, label
            assert not any(word in reply.lower() for word in BANNED), label
            if expect["action"] == "care":
                assert not decision["must_drive"] and question_count(reply) == 0, label
            else:
                assert decision["must_drive"], label
                assert question_count(reply) == 1 or any(m in reply.casefold() for m in MARKERS), label
            assert language == turn["signals"]["language"], label
            if expect.get("about_pai"):
                assert "<about_pai>" in prompts[0], label
            else:
                assert "<about_pai>" not in prompts[0], label
        with student.factory() as db:
            types = {item.item_type for item in VaultItemService(db).active(student.workspace_id)}
            records = StudentRecordService(db).snapshot(student.workspace_id)
            types |= {kind for kind, rows in records.items() if rows}
    assert set(case["expect_vault_types"]) <= types
