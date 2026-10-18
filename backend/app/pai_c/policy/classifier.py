"""One text-only classification before the deterministic conversation decision."""
import asyncio
import logging
from pathlib import Path
from typing import Literal
import json

from pydantic import BaseModel, ConfigDict
from app.config import config
from app.inference.gateway import complete
from app.pai_c.understanding.data import DATA_DIR

logger = logging.getLogger(__name__)

Area = Literal[tuple(json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8")))]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SafetyResult(StrictModel):
    level: Literal["none", "concern", "urgent"]
    category: Literal["self_harm", "harm_to_others", "abuse", "acute_distress", "other"] | None


class Request(StrictModel):
    text: str
    kind: Literal["information", "task", "decision_help", "other"]
    needs_research: bool
    needs_context: bool


from pydantic import PrivateAttr


class Signals(StrictModel):
    _fallback: bool = PrivateAttr(default=False)
    safety: SafetyResult
    intent: Literal["sharing", "asking_info", "asking_task", "deciding", "pushback", "short_reply", "greeting", "other"]
    emotion: Literal["neutral", "positive", "stressed", "frustrated", "distressed"]
    request: Request | None
    mentioned_areas: list[Area]
    declined_area: Area | None
    opened_thread: Area | None = None


def fallback_signals():
    result = Signals.model_validate_json(Path(__file__).with_name("classifier_fallback.json").read_text(encoding="utf-8"))
    result._fallback = True
    return result


async def classify(student_text, recent_turns):
    history = [{"role": row["role"], "text": row["content"]} for row in recent_turns[-4:]]
    try:
        raw = await asyncio.wait_for(complete(
            role="classifier", phase="classifier",
            system_prompt=Path(__file__).with_name("prompts").joinpath("turn_classifier.md").read_text(encoding="utf-8"),
            messages=[{"role": "user", "content": json.dumps({
                "recent_turns": history, "student_message": student_text}, ensure_ascii=False)}],
            response_format={"type": "json_object"}),
            timeout=config.PAI_CLASSIFIER_TIMEOUT_MS / 1000)
        return Signals.model_validate_json(raw)
    except Exception as exc:
        logger.warning("classifier_error error_type=%s", type(exc).__name__)
        signals = fallback_signals()
        signals._fallback = True
        return signals
