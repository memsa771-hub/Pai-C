"""Only the chat follows the student's language; everything stored for the
workspace is written in the workspace language from data. Fake models only."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.memory.extraction_context import TurnContext
from app.memory.extractor import SYSTEM_PROMPT, extract_candidates
from app.pai_c.deep.context import build_context
from app.pai_c.deep.prompts import load_prompt
from app.workspace_language import workspace_language, workspace_language_block
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import prepare


def test_language_comes_from_data():
    import app
    data = json.loads((Path(app.__file__).parent / "workspace_language.json").read_text(encoding="utf-8"))
    assert workspace_language() == {"language": data["language"], "style": data["style"]}
    assert json.loads(workspace_language_block().removeprefix("<workspace_language>").removesuffix("</workspace_language>")) == workspace_language()


def test_prompts_that_write_for_the_workspace_name_the_workspace_language():
    assert "<workspace_language>" in SYSTEM_PROMPT
    for name in ("planner", "path_analyzer"):
        assert "<workspace_language>" in load_prompt(name), name
    # The analyzer's chat message still follows the student (the stored chat language).
    assert "in the language and script given in <chat_language>" in load_prompt("path_analyzer")


@pytest.mark.asyncio
async def test_extractor_receives_the_workspace_language():
    turn = TurnContext(workspace_id="w", user_event_id="e", user_text="Abbu fees zyada nahi de sakte")
    model = AsyncMock(return_value=json.dumps({"candidates": []}))
    with patch("app.memory.extractor.chat_completion", model), \
         patch("app.memory.extractor._model_config", return_value=("test", "test", None)):
        await extract_candidates(turn, set(), [])
    assert workspace_language_block() in model.call_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_the_voice_context_does_not_carry_the_workspace_language():
    # The old Mirror job was the only context with it; the Mirror text job
    # reads the state card, which is in English already.
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = prepare(student, db)
        voice = await build_context(db, student.workspace_id, turn)
    assert "<workspace_language>" not in voice.text
