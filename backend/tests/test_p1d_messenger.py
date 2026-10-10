"""Offline P1d messenger checks."""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

from app.pai_c import posting


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_private_posting_is_not_imported():
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom):
                assert all(alias.name != "_post_response" for alias in node.names), str(path)


def test_counselor_visible_event_construction_only_in_messenger():
    for path in (APP / "pai_c").rglob("*.py"):
        if path.name == "posting.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Call):
                assert not any(keyword.arg == "type" and isinstance(keyword.value, ast.Constant)
                               and keyword.value.value == "workspace.message.posted"
                               for keyword in node.keywords), str(path)


@pytest.mark.asyncio
async def test_messenger_preserves_every_argument():
    post = AsyncMock(return_value="event")
    with patch.object(posting, "_post_response", post):
        result = await posting.send_to_student(None, "workspace", "channel", "pai", "reply", 2,
            attachments=[{"id": "file"}], message_type="document_processed",
            metadata={"voice_delegation_id": "voice"}, extra_payload={"version": 1})
    assert result == "event"
    post.assert_awaited_once_with(None, "workspace", "channel", "pai", "reply", 2,
        attachments=[{"id": "file"}], message_type="document_processed",
        metadata={"voice_delegation_id": "voice"}, extra_payload={"version": 1})


