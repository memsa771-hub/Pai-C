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
from app.models import Workspace
from app.security.event_identity import resolve_human
from app.routers.network import _workspace_filter
from app.pai_c.voice_context import _target_for_conversation, _recent_dialogue, _VOICE_INSTRUCTIONS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/counselor/voice", tags=["Counselor voice"])

_LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"


class VoiceSessionRequest(BaseModel):
    network: str = Field(min_length=1, max_length=128)
    conversation: str = Field(min_length=1, max_length=256)
    sdp: str = Field(min_length=20, max_length=100_000)


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
