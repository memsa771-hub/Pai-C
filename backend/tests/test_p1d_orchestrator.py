"""Offline P1d orchestrator checks."""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

from app.pai_c import orchestrator, posting


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_external_inputs_only_import_orchestrator():
    blocked = {"app.pai_c.runtime", "app.pai_c.handoff", "app.pai_c.deep.turn"}
    for path in APP.rglob("*.py"):
        if "pai_c" in path.relative_to(APP).parts:
            continue
        assert not blocked.intersection(imports(path)), str(path)


@pytest.mark.asyncio
async def test_orchestrator_student_preserves_arguments():
    model = AsyncMock()
    with patch("app.pai_c.runtime.run_counselor", model):
        await orchestrator.handle_student_message("workspace", {"id": "event"})
    model.assert_awaited_once_with("workspace", {"id": "event"})


@pytest.mark.asyncio
async def test_orchestrator_research_preserves_arguments():
    model = AsyncMock(return_value="reply")
    with patch("app.pai_c.handoff.explain_result", model):
        assert await orchestrator.handle_research_result("workspace", [], {"result": 1}) == "reply"
    model.assert_awaited_once_with("workspace", [], {"result": 1})


@pytest.mark.asyncio
async def test_orchestrator_document_preserves_arguments():
    post = AsyncMock(return_value="event")
    with patch.object(posting, "send_to_student", post):
        assert await orchestrator.handle_document_update(None, "workspace", "channel", "pai",
                                                        "reply", depth=0) == "event"
    post.assert_awaited_once_with(None, "workspace", "channel", "pai", "reply", depth=0)
