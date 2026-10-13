"""Safety classification; input is text only, never a DB session."""
from pathlib import Path
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict
from app.inference.gateway import complete


class SafetyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    level: Literal["none", "concern", "urgent"]
    category: Literal["self_harm", "harm_to_others", "abuse", "acute_distress", "other"] | None


async def check_message(student_text, recent_turns) -> SafetyResult:
    history = [{"role": row["role"], "text": row["content"]} for row in recent_turns[-4:]]
    raw = await complete(role="safety", phase="safety",
        system_prompt=Path(__file__).with_name("prompts").joinpath("safety.md").read_text(encoding="utf-8"),
        messages=[{"role": "user", "content": json.dumps({
            "recent_turns": history, "student_message": student_text}, ensure_ascii=False)}],
        response_format={"type": "json_object"})
    return SafetyResult.model_validate_json(raw)
