"""Explicit, isolated Compose smoke entry point. Never use for deployment.

The real app, database and event pipeline run with fake identity/model providers.
All inference factories and external hostname resolution are blocked.
"""

import json
import os
import socket

if os.environ.get("PAI_OFFLINE_STARTUP_CHECK") != "1":
    raise RuntimeError("This test entry point requires PAI_OFFLINE_STARTUP_CHECK=1")

_resolve = socket.getaddrinfo


def local_addresses_only(host, *args, **kwargs):
    if isinstance(host, bytes):
        host = host.decode("ascii")
    if host not in {"postgres", "localhost", "127.0.0.1", "::1", "0.0.0.0", None}:
        raise RuntimeError("Outbound connections forbidden during offline startup checks")
    return _resolve(host, *args, **kwargs)


socket.getaddrinfo = local_addresses_only

from app.inference import client
from app.security.identity import AuthenticatedIdentity, SupabaseIdentityVerifier


def deny_model_client(*args, **kwargs):
    raise RuntimeError("Real model clients are forbidden during offline startup checks")


async def fake_completion(**kwargs):
    return json.dumps({"reply": "What did you enjoy most about your studies?", "action": {"type": "none"}})


async def fake_tool_completion(**kwargs):
    return {"role": "assistant", "content": await fake_completion(**kwargs)}


def fake_identity(self, token):
    if token != "offline-provider-token":
        return None
    return AuthenticatedIdentity("supabase", "00000000-0000-0000-0000-000000000001",
                                 "offline-student@example.invalid", True, "Offline Student")


client.create_client = deny_model_client
client.chat_completion = fake_completion
client.chat_completion_tools = fake_tool_completion
SupabaseIdentityVerifier.verify = fake_identity

from app.main import app
from app.routers import counselor_voice

counselor_voice._LIVE_SESSIONS_URL = "http://127.0.0.1:8000/_offline/live"


@app.post("/_offline/live")
async def fake_voice_handshake():
    return {"session": {"id": "offline-voice-session"},
            "transport": {"sdp": "v=0\r\ns=offline voice answer\r\n"}}
