"""Voice setup stays owner-only and returns a WebRTC answer without the key."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from app.routers.counselor_voice import VoiceSessionRequest, _recent_dialogue, _target_for_conversation, create_voice_session
from app.counseling.runtime import _voice_reply_metadata
from app.security.event_identity import Actor

WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"


def test_voice_route_is_mounted():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post("/v1/counselor/voice/session", json={}).status_code == 422


def test_counselor_reply_keeps_only_bounded_voice_correlation():
    assert _voice_reply_metadata({"metadata": {"voice_delegation_id": "item_123"}}) == {
        "voice_delegation_id": "item_123"}
    assert _voice_reply_metadata({"metadata": {"voice_delegation_id": "x" * 129}}) is None
    assert _voice_reply_metadata({"metadata": {"voice_delegation_id": 42}}) is None


def test_dm_cannot_open_channel_voice_session():
    db = Mock()
    workspace = SimpleNamespace(id="workspace")
    assert _target_for_conversation(db, workspace, "dm:human:user,openagents:pai") is None
    assert _target_for_conversation(db, workspace, "dm:human:user,openagents:other") is None
    db.execute.assert_not_called()


def test_live_receives_only_recent_chat_context_as_history():
    db = Mock()
    db.execute.return_value.scalars.return_value.all.return_value = [
        SimpleNamespace(source="openagents:pai", payload={"content": "Let us compare the costs."}),
        SimpleNamespace(source="openagents:pai", payload={"content": "I can help with that. Let's work from what you've shared and take the next useful step."}),
        SimpleNamespace(source="openagents:pai", payload={"content": "private state", "message_type": "status"}),
        SimpleNamespace(source="human:owner", payload={"content": "I prefer CS."}),
    ]
    history = _recent_dialogue(db, "workspace", "channel/pai-counselor", "owner")
    assert history == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "I prefer CS."}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Let us compare the costs."}]},
    ]


def test_session_creation_uses_server_key_and_client_delegation():
    workspace = SimpleNamespace(id=WORKSPACE_ID, owner_user_id="owner")
    channel = SimpleNamespace(master_agent="pai")
    db = Mock()
    db.execute.side_effect = [
        Mock(scalar_one_or_none=Mock(return_value=workspace)),
        Mock(scalar_one_or_none=Mock(return_value=channel)),
        Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[])))),
    ]
    captured = {}

    def provider(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={
            "session": {"id": "live-1"},
            "transport": {"sdp": "answer-sdp"},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    body = VoiceSessionRequest(network="student-slug", conversation="pai-counselor", sdp="offer-sdp-with-enough-length")
    with patch("app.routers.counselor_voice.resolve_human", return_value=Actor("human:owner", "human", "owner")), \
         patch("app.routers.counselor_voice.httpx.AsyncClient", return_value=client), \
         patch("app.routers.counselor_voice.config.PAI_ENABLED", True), \
         patch("app.routers.counselor_voice.config.PAI_API_KEY", "server-secret"):
        result = asyncio.run(create_voice_session(body, db, "Bearer owner-token"))

    assert result["data"] == {"session_id": "live-1", "sdp": "answer-sdp"}
    assert "server-secret" not in str(result)
    assert captured["url"] == "https://api.openai.com/v1/live/sessions"
    assert captured["authorization"] == "Bearer server-secret"
    assert captured["body"]["session"]["model"] == "gpt-live-1"
    assert captured["body"]["session"]["delegation"] == {"type": "client"}
    assert captured["body"]["transport"] == {"type": "webrtc", "sdp": body.sdp}


def test_unverified_student_cannot_create_session():
    db = Mock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(id=WORKSPACE_ID)
    body = VoiceSessionRequest(network=WORKSPACE_ID, conversation="pai-counselor", sdp="offer-sdp-with-enough-length")
    with patch("app.routers.counselor_voice.resolve_human", return_value=None):
        result = asyncio.run(create_voice_session(body, db, "Bearer invalid"))
    assert result.status_code == 401
