"""Language is generic (BETA_CONVERSATION_SPEC 2.5): PAI writes in the
language of the student's latest message, every message to the student
follows it, and nothing in code assumes one language. Offline only."""
import ast
import os
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import EventRecord, Workspace
from app.pai_c import language
from app.pai_c.mirror.text_job import mirror_text_job
from app.pai_c.policy import controller
from scripts.counselor_eval_support import StudentSession
from tests.test_director_drive import signals
from tests.test_mirror_text_job import _job, _reply, _seed

APP = Path(__file__).resolve().parents[1] / "app"
LANGUAGE_NAMES = ("Urdu",)
ROMAN = {"code": "ur", "script": "latin"}


def _docstrings(tree):
    nodes = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, nodes) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}


def test_no_language_name_literal_in_backend_code():
    """String literals in app code never name a language (docstrings may
    explain one, and data files hold the codes)."""
    found = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
                    and any(name in node.value for name in LANGUAGE_NAMES)):
                found.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert found == []


def test_chat_prompts_name_a_language_only_in_marked_examples():
    folders = [APP / "pai_c/voice/prompts", APP / "pai_c/policy/prompts", APP / "pai_c/policy/actions",
               APP / "pai_c/deep/prompts"]
    for path in (p for folder in folders for p in folder.glob("*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if any(name in line for name in LANGUAGE_NAMES):
                assert "example" in line.lower(), f"{path.name}: {line[:80]}"


def test_blocked_script_replacement_defaults_to_the_students_language(monkeypatch):
    from app.config import Config
    assert Config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT == "" or "PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT" in os.environ
    monkeypatch.setattr(config, "PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT", "")
    try:
        config.validate_startup()
    except RuntimeError as exc:
        assert "REPLACEMENT" not in str(exc)
    from app.pai_c.deep.prompts import load_prompt
    assert "student's language and script" in load_prompt("language_retry")


@pytest.mark.asyncio
async def test_context_language_section_and_no_replacement_by_default(monkeypatch):
    from app.pai_c.deep.context import build_context
    from tests.test_counselor_deep_pr3 import _turn
    monkeypatch.setattr(config, "PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT", "")
    with StudentSession() as student, student.factory() as db:
        language.set_chat_language(db, student.workspace_id, ROMAN)
        db.commit()
        context = await build_context(db, student.workspace_id, _turn(student))
    policy = json.loads(context.text.split("<language_policy>")[1].split("</language_policy>")[0])
    assert "replacement" not in policy
    assert json.loads(context.text.split("<language>")[1].split("</language>")[0]) == ROMAN


@pytest.mark.asyncio
async def test_language_follows_latest_turn(monkeypatch):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    turns = [("Main FSc kar raha hoon", ROMAN), ("Actually let me write in English", {"code": "en", "script": "latin"}),
             ("میں انجینئر بننا چاہتا ہوں", {"code": "ur", "script": "arabic"})]
    seen = []
    with StudentSession() as student:
        async def writer(**kwargs):
            context = kwargs["system_prompt"].split("<context>" + chr(10) + "<today>", 1)[1]
            seen.append(json.loads(context.split("<language>")[1].split("</language>")[0]))
            questions = ["Tumhe kya pasand hai?", "Which subjects do you find easiest?", "آپ کے والدین کیا چاہتے ہیں؟"]
            return json.dumps({"reply": questions[len(seen) - 1], "moves": ["ask"], "action": {"type": "none"}})
        for text, lang in turns:
            sig = signals(language=lang)
            with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
                 patch("app.pai_c.deep.turn.chat_completion", writer):
                await student.turn(text)
            with student.factory() as db:
                assert db.get(Workspace, student.workspace_id).chat_language == lang
    assert seen == [lang for _, lang in turns]


@pytest.mark.asyncio
async def test_render_copy_once_per_language_and_english_never_calls_the_model():
    model = AsyncMock(return_value=json.dumps({"text": "Yeh rahe tumhare paths."}))
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        with patch("app.inference.gateway.complete", model):
            assert await language.render_copy(db, ws, "k", "Here are your paths.") == "Here are your paths."
            language.set_chat_language(db, ws, ROMAN)
            db.commit()
            assert await language.render_copy(db, ws, "k", "Here are your paths.") == "Yeh rahe tumhare paths."
            assert await language.render_copy(db, ws, "k", "Here are your paths.") == "Yeh rahe tumhare paths."
        assert model.await_count == 1
        assert json.loads(model.await_args.kwargs["messages"][0]["content"])["language"] == ROMAN
        with patch("app.inference.gateway.complete", AsyncMock(side_effect=RuntimeError("down"))):
            assert await language.render_copy(db, ws, "other", "Open the Roadmap.") == "Open the Roadmap."


def test_onboarding_language_detection_is_data():
    assert language.detected_language("Lahore") is None
    assert language.detected_language("main parhai kar raha hoon aur mujhe pasand hai") == ROMAN


@pytest.mark.asyncio
async def test_mirror_text_is_written_in_the_chat_language():
    sentences = ["Tum FSc Pre-Engineering mein ho aur 82% marks hain.", "Tumhe robotics pasand hai.",
                 "Goals abhi khule hain."]
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        language.set_chat_language(db, ws, ROMAN)
        db.commit()
        job = _job(db, ws)
        model = AsyncMock(return_value=_reply(sentences))
        with patch("app.pai_c.mirror.text_job.chat_completion", model):
            result = await mirror_text_job(job, db)
    assert result["status"] == "written" and model.await_count == 1
    assert json.dumps(ROMAN) in model.await_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_needs_education_message_is_rendered_in_the_chat_language():
    from app.pai_c.paths import analyzer
    copy = controller.load_data("path_analyzer.json")["needs_education_messages"]["education"]
    model = AsyncMock(return_value=json.dumps({"text": "Pehle apni taleem batao."}))
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        language.set_chat_language(db, ws, ROMAN)
        db.commit()
        job = SimpleNamespace(id="job-1", workspace_id=ws)
        with patch("app.inference.gateway.complete", model):
            result = await analyzer._needs_education(db, job, {"channel": "channel/pai-counselor", "reason": "asked"}, [])
        assert result["status"] == "needs_education"
        assert student.transcript[-1]["content"] == "Pehle apni taleem batao."
        assert json.loads(model.await_args.kwargs["messages"][0]["content"])["text"] == copy
