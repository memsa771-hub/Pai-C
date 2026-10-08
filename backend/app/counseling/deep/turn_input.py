"""Channel-neutral student turns and causally ordered Counselor history."""

from dataclasses import dataclass

from sqlalchemy import select

from app.models import EventRecord
from app.counseling.deep.polish import is_counselor_fallback


@dataclass(frozen=True)
class CounselorTurnInput:
    channel: str  # Delivery only; not supplied to the Counselor model.
    workspace_id: str
    student_text: str
    attachments: tuple[dict, ...]
    session_id: str | None
    source_event_id: str
    timestamp: int | None
    source: str
    voice: bool = False


def shared_history(db, turn: CounselorTurnInput, owner_id: str,
                   *, limit: int = 24) -> list[dict]:
    """Student and PAI chat across channels in this workspace, causally prior."""
    query = select(EventRecord).where(
        EventRecord.network_id == turn.workspace_id,
        EventRecord.type == "workspace.message.posted",
        EventRecord.source.in_((f"human:{owner_id}", "openagents:pai")),
    )
    if turn.timestamp is not None:
        query = query.where(EventRecord.timestamp < turn.timestamp)
    else:
        query = query.where(EventRecord.id != turn.source_event_id)
    rows = db.execute(query.order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
                      .limit(limit * 3)).scalars().all()
    history = []
    for row in rows:
        payload = row.payload or {}
        text = payload.get("content")
        message_type = payload.get("message_type", "chat")
        if ((message_type != "chat" and not (
                message_type in {"operator_result", "counselor_mirror"} and row.source == "openagents:pai"))
                or not isinstance(text, str)
                or not text.strip() or text.startswith("[Error]")
                or (row.source == "openagents:pai" and is_counselor_fallback(text))):
            continue
        history.append({"role": "assistant" if row.source == "openagents:pai" else "user",
                        "content": text[:1500], "target": row.target,
                        "session_id": (row.metadata_ or {}).get("voice_session_id")
                        or (row.metadata_ or {}).get("session_id")})
        if len(history) == limit:
            break
    history.reverse()
    return history


def _returning(history: list[dict], turn: CounselorTurnInput) -> bool:
    students = [row for row in history if row["role"] == "user"]
    if not students:
        return False
    return bool(students[-1]["target"] != turn.channel or (
        turn.session_id and students[-1].get("session_id")
        and students[-1]["session_id"] != turn.session_id))
