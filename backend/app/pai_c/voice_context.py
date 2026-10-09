"""Counselor-only voice history and channel authorization helpers."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Channel, ChannelMember, EventRecord, Workspace
from app.services.pai import PAI_AGENT_NAME
from app.pai_c.deep.polish import is_counselor_fallback


_VOICE_INSTRUCTIONS = (
    "You are the audio transport for PAI Counselor. Transcribe each completed "
    "student turn and delegate it to the client. Wait for client commentary. "
    "Speak that commentary verbatim, with no added words, omissions, translation, "
    "advice, or paraphrase. When interrupted, stop speaking and listen to the "
    "new student turn. Never speak the Profile automatically."
)


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
        if payload.get("message_type", "chat") not in {"chat", "counselor_mirror"}:
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
