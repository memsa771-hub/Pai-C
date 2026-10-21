"""The Counselor points the student to a place in their workspace: a known
view key, shown as a link, never a route or a system name. Fake models only."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import EventRecord
from app.pai_c.deep.actions import shown_place, workspace_places
from app.pai_c.policy.classifier import fallback_signals
from scripts.counselor_eval_support import StudentSession

ROOT = Path(__file__).resolve().parents[2]


def test_places_are_workspace_views_described_for_students():
    places = workspace_places()
    copy = ROOT / "frontend/components/counselor/workspace/copy.json"
    if copy.exists():
        assert set(places) <= set(json.loads(copy.read_text(encoding="utf-8"))["nav"])
    assert all(text and "/" not in text for text in places.values())


@pytest.mark.parametrize("action,expected", [
    ({"type": "show_place", "place": "paths"}, "paths"),
    ({"type": "show_place", "place": "admin"}, None),
    ({"type": "show_place"}, None),
    ({"type": "none", "place": "paths"}, None),
])
def test_only_known_places_are_shown(action, expected):
    assert shown_place(action) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["guided", "strict"])
@pytest.mark.parametrize("place,linked", [("files", True), ("operator-console", False)])
async def test_reply_links_to_a_known_place_and_context_lists_them(monkeypatch, mode, place, linked):
    monkeypatch.setattr(config, "PAI_POLICY_MODE", mode)
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    prompts = []

    async def voice(**kwargs):
        prompts.append(kwargs["system_prompt"])
        return json.dumps({"reply": "You can upload your marksheet in Documents.", "moves": ["give"],
                           "action": {"type": "show_place", "place": place}})

    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=fallback_signals().model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", voice):
            await student.turn("Marksheet kahan upload karun?")
        with student.factory() as db:
            reply = db.scalar(select(EventRecord).where(
                EventRecord.source == "openagents:pai", EventRecord.type == "workspace.message.posted"))
            assert ((reply.metadata_ or {}).get("workspace_place") == place) is linked
            recorded = db.scalar(select(EventRecord).where(EventRecord.type == "counselor.action.show_place"))
            assert recorded.payload["status"] == ("offered" if linked else "ignored")
    assert "<workspace_places>" in prompts[0] and '"files"' in prompts[0]
