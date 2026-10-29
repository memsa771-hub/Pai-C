"""The opening knows the student from the first message (BETA_CONVERSATION_SPEC 2.1):
name, education line as the Mirror shows it, city; one open question; the
chat or onboarding language. Offline: the model is mocked."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import User
from app.pai_c import language, opening
from app.pai_c.policy import controller
from scripts.counselor_eval_support import StudentSession
from tests.test_mirror_engine import _education

ABOUT_YOU = controller.bank_item("about_you")["prompt"]


def _fact(db, ws, key, value):
    candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type="vault_fact", key=key,
        proposed_value=value, confidence=1, source_type="user_explicit", input_channel="profile",
        evidence={"quote": value, "capture": "onboarding"}, allow_user_explicit=True)
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()


def _section(prompt, name):
    return json.loads(prompt.split(f"<{name}>", 1)[1].split(f"</{name}>", 1)[0])


async def _open(student, db):
    model = AsyncMock(return_value=json.dumps({"reply": "Salam Ali. Tell me about yourself?", "moves": ["ask"],
                                               "action": {"type": "none"}}))
    job = SimpleNamespace(id="opening", workspace_id=student.workspace_id, attempts=1, max_attempts=3)
    with patch.object(opening, "complete", model):
        assert (await opening.opening_job(job, db))["status"] == "posted"
    return model.await_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_opening_names_the_education_line_and_asks_one_open_question():
    with StudentSession() as student, student.factory() as db:
        db.get(User, student.user_id).display_name = "Ali"
        db.commit()
        _education(db, student.workspace_id)
        _fact(db, student.workspace_id, "location.current_city", "Lahore")
        prompt = await _open(student, db)
    core = _section(prompt, "student_core")
    assert core["name"] == "Ali"
    assert "Pre-Engineering" in core["education_line"]
    assert "Lahore" in core["facts"].values()
    assert ABOUT_YOU in prompt and "Never ask anything <student_core> already answers" in prompt
    # Only the script of the student's own words (city, name), never a language code.
    assert _section(prompt, "opening_language") == {"code": None, "script": "latin"}
    assert "Lahore" in _section(prompt, "student_words")


@pytest.mark.asyncio
async def test_opening_language_is_the_chat_language_else_the_script_of_the_students_words():
    words = "\u0645\u06cc\u06ba \u067e\u0691\u06be \u0631\u06c1\u0627 \u06c1\u0648\u06ba"
    with StudentSession() as student, student.factory() as db:
        # The Vault keeps English, so the student's own script is seen through their typed words.
        with patch("app.pai_c.memory.onboarding_words", return_value=[words]):
            prompt = await _open(student, db)
        # Script only, never a language code: the Writer matches the student's own words.
        assert _section(prompt, "opening_language") == {"code": None, "script": "arabic"}
        assert words in _section(prompt, "student_words")
        assert "same language and script as the student's own words" in prompt
    with StudentSession() as student, student.factory() as db:
        language.set_chat_language(db, student.workspace_id, {"code": "ps", "script": "arabic"})
        db.commit()
        prompt = await _open(student, db)
        assert _section(prompt, "opening_language") == {"code": "ps", "script": "arabic"}



@pytest.mark.asyncio
async def test_the_opening_posts_exactly_one_question():
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=json.dumps({
            "reply": "Salam Ali. Main PAI hoon. Apne baare mein batao, aaj kal kya karte ho?",
            "next_step": "Aur tumhe kya pasand hai?", "moves": ["ask"], "action": {"type": "none"}}))
        job = SimpleNamespace(id="opening", workspace_id=student.workspace_id, attempts=1, max_attempts=3)
        with patch.object(opening, "complete", model):
            assert (await opening.opening_job(job, db))["status"] == "posted"
        posted = student.transcript[-1]["content"]
        assert posted.count("?") == 1 and posted.endswith("aaj kal kya karte ho?")
        assert "no separate next step" in model.await_args.kwargs["system_prompt"]



@pytest.mark.asyncio
async def test_the_opening_metadata_has_no_step_when_it_ends_with_its_question():
    from sqlalchemy import select
    from app.models import EventRecord
    with StudentSession() as student, student.factory() as db:
        await _open(student, db)
        row = db.scalar(select(EventRecord).where(EventRecord.source == "openagents:pai",
                                                  EventRecord.type == "workspace.message.posted"))
        assert "next_step" not in (row.metadata_ or {})
