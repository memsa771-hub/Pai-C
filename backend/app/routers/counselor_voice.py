"""Authenticated GPT-Live WebRTC setup for the existing PAI Counselor.

The browser receives only an SDP answer. The permanent OpenAI key stays here;
student turns still enter the ordinary workspace event and Counselor pipeline.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.config import config
from app.database import get_db
from app.models import Channel, ChannelMember, EventRecord, Workspace
from app.security.event_identity import resolve_human
from app.services.pai import PAI_AGENT_NAME
from app.routers.network import _workspace_filter
from app.counseling.turn_contract import is_counselor_fallback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/counselor/voice", tags=["Counselor voice"])

_LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"
_VOICE_INSTRUCTIONS = (
    "You are the audio transport for PAI Counselor. Transcribe each completed "
    "student turn and delegate it to the client. Wait for client commentary. "
    "Speak that commentary verbatim, with no added words, omissions, translation, "
    "advice, or paraphrase. When interrupted, stop speaking and listen to the "
    "new student turn. Never speak the Profile automatically."
)


class VoiceSessionRequest(BaseModel):
    network: str = Field(min_length=1, max_length=128)
    conversation: str = Field(min_length=1, max_length=256)
    sdp: str = Field(min_length=20, max_length=100_000)


def _target_for_conversation(db: Session, workspace: Workspace, conversation: str) -> str | None:
    """Allow only an active Counselor channel in the owner's workspace."""
    if conversation.startswith("dm:"):
        return None
    channel = db.execute(select(Channel).where(
        Channel.workspace_id == workspace.id,
        Channel.name == conversation,
        Channel.status == "active",
    )).scalar_one_or_none()
    if channel is None:
        return None
    if channel.master_agent == PAI_AGENT_NAME:
        return f"channel/{conversation}"
    member = db.execute(select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.agent_name == PAI_AGENT_NAME,
    )).scalar_one_or_none()
    return f"channel/{conversation}" if member is not None else None


def _recent_dialogue(db: Session, workspace_id: str, target: str, owner_id: str) -> list[dict]:
    """Supply only chat dialogue for conversational continuity, never Vault/Profile."""
    rows = db.execute(select(EventRecord).where(
        EventRecord.network_id == workspace_id,
        EventRecord.target == target,
        EventRecord.type == "workspace.message.posted",
        EventRecord.source.in_((f"human:{owner_id}", f"openagents:{PAI_AGENT_NAME}")),
    ).order_by(EventRecord.timestamp.desc()).limit(8)).scalars().all()
    history = []
    for row in reversed(rows):
        payload = row.payload or {}
        if payload.get("message_type", "chat") != "chat":
            continue
        content = str(payload.get("content") or "").strip()
        if content and not content.startswith("[Error]") and not is_counselor_fallback(content):
            student = row.source == f"human:{owner_id}"
            history.append({
                "type": "message",
                "role": "user" if student else "assistant",
                "content": [{"type": "input_text" if student else "output_text",
                             "text": content[:650]}],
            })
    return history


@router.post("/session")
async def create_voice_session(
    body: VoiceSessionRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    workspace = db.execute(select(Workspace).where(_workspace_filter(body.network))).scalar_one_or_none()
    if workspace is None:
        return json_response(ResponseCode.NOT_FOUND, "Workspace not found")
    actor = resolve_human(db, workspace, authorization)
    if actor is None:
        return json_response(ResponseCode.UNAUTHORIZED, "Sign in to talk to PAI")
    target = _target_for_conversation(db, workspace, body.conversation)
    if target is None:
        return json_response(ResponseCode.FORBIDDEN, "This is not a PAI Counselor conversation")
    if not config.PAI_ENABLED or not config.PAI_API_KEY:
        return json_response(ResponseCode.INTERNAL_ERROR, "PAI voice is unavailable")

    recent = _recent_dialogue(db, str(workspace.id), target, actor.user_id or "")
    db.rollback()  # Release the DB connection before the external session handshake.
    payload = {
        "session": {
            "model": "gpt-live-1",
            "instructions": _VOICE_INSTRUCTIONS,
            "delegation": {"type": "client"},
            "input": recent,
        },
        "transport": {"type": "webrtc", "sdp": body.sdp},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _LIVE_SESSIONS_URL,
                headers={"Authorization": f"Bearer {config.PAI_API_KEY}"},
                json=payload,
            )
            response.raise_for_status()
            live = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("voice session setup failed: %s", type(exc).__name__)
        return json_response(ResponseCode.INTERNAL_ERROR, "Could not connect voice right now")

    session_id = live.get("session", {}).get("id")
    answer = live.get("transport", {}).get("sdp")
    if not isinstance(session_id, str) or not isinstance(answer, str):
        logger.error("voice session setup returned an incomplete answer")
        return json_response(ResponseCode.INTERNAL_ERROR, "Could not connect voice right now")
    return success_response({"session_id": session_id, "sdp": answer})
