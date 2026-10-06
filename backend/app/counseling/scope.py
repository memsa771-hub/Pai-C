"""Small, bounded scope classification; no counseling decisions are delegated."""

import json

from app.config import config
from app.inference.client import chat_completion


async def classify_scope(student_text: str, history: list[dict]) -> str:
    raw = await chat_completion(
        api_key=config.PAI_API_KEY,
        model=config.PAI_COUNSELOR_AUX_MODEL or config.PAI_MODEL,
        base_url=config.PAI_BASE_URL,
        messages=[{"role": "user", "content": json.dumps({
            "recent_turns": history[-6:], "student_message": student_text,
        }, ensure_ascii=False)}],
        system_prompt=(
            "Classify the current student message. crisis means immediate danger or "
            "self-harm; wellbeing means distress needing a supportive pause; off_topic "
            "means unrelated to education or career. Education, career, and normal "
            "feelings about them are in_scope. Return JSON only."
        ),
        max_tokens=60,
        response_format={"type": "json_schema", "json_schema": {
            "name": "pai_counselor_scope", "strict": True,
            "schema": {"type": "object", "properties": {"scope": {
                "type": "string", "enum": ["in_scope", "off_topic", "wellbeing", "crisis"],
            }}, "required": ["scope"], "additionalProperties": False},
        }},
    )
    value = json.loads(raw).get("scope")
    if value not in {"in_scope", "off_topic", "wellbeing", "crisis"}:
        raise ValueError("Invalid Counselor scope")
    return value
