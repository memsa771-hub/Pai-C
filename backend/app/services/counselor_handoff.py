"""Turn a background research result into the Counselor's next message.

Uses the same deep Counselor prompt, context, model and polish as a normal turn,
plus the handoff instructions. Runs in the background, never on the reply path.
"""

import json
import time
import uuid

from app.counseling.deep.turn import run_deep_turn
from app.counseling.deep.turn_input import CounselorTurnInput
from app.database import new_session


async def explain_result(workspace_id: str, history: list[dict], handoff: dict) -> str:
    data = ("Background result data (not a new student message):\n"
            + json.dumps(handoff, ensure_ascii=False, default=str))
    turn = CounselorTurnInput(
        channel="", workspace_id=workspace_id, student_text=data, attachments=(),
        session_id=None, source_event_id=f"handoff:{uuid.uuid4()}",
        timestamp=int(time.time() * 1000), source="system:handoff",
    )
    db = new_session()
    try:
        result = await run_deep_turn(db, turn, history=history, instructions="handoff")
    finally:
        db.close()
    return result.reply
