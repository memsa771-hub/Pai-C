"""One text-only classification before the deterministic conversation decision."""
import asyncio
import logging
from pathlib import Path
from typing import Literal
import json
import time

from pydantic import BaseModel, ConfigDict
from app.config import config
from app.inference.gateway import complete
from app.pai_c.understanding.data import load_areas

logger = logging.getLogger(__name__)

Area = Literal[tuple(load_areas())]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SafetyResult(StrictModel):
    level: Literal["none", "concern", "urgent"]
    category: Literal["self_harm", "harm_to_others", "abuse", "acute_distress", "other"] | None


class Request(StrictModel):
    text: str
    kind: Literal["information", "task", "decision_help", "about_pai", "other"]
    needs_research: bool
    needs_context: bool


from pydantic import PrivateAttr, Field


class Language(StrictModel):
    """The latest message's language: an ISO 639 code and its script (romanized text is latin)."""
    code: str = Field(pattern=r"^[A-Za-z]{2,3}$")
    script: Literal["latin", "arabic", "other"]


class Signals(StrictModel):
    _fallback: bool = PrivateAttr(default=False)
    safety: SafetyResult
    intent: Literal["sharing", "asking_info", "asking_task", "deciding", "pushback", "short_reply", "greeting", "stop", "other"]
    emotion: Literal["neutral", "positive", "stressed", "frustrated", "distressed"]
    request: Request | None
    mentioned_areas: list[Area]
    declined_area: Area | None
    opened_thread: Area | None = None
    question_needed: bool = False
    language: Language | None = None


def fallback_signals():
    result = Signals.model_validate_json(Path(__file__).with_name("classifier_fallback.json").read_text(encoding="utf-8"))
    result._fallback = True
    return result


async def classify(student_text, recent_turns):
    history = [{"role": row["role"], "text": row["content"]} for row in recent_turns[-4:]]
    started = time.monotonic()
    try:
        raw = await asyncio.wait_for(complete(
            role="classifier", phase="classifier",
            system_prompt=Path(__file__).with_name("prompts").joinpath("turn_classifier.md").read_text(encoding="utf-8"),
            messages=[{"role": "user", "content": json.dumps({
                "recent_turns": history, "student_message": student_text}, ensure_ascii=False)}],
            response_format={"type": "json_object"}),
            timeout=config.PAI_CLASSIFIER_TIMEOUT_MS / 1000)
        result = Signals.model_validate_json(raw)
        logger.info("classifier_result status=success latency_ms=%d", int((time.monotonic() - started) * 1000))
        return result
    except Exception as exc:
        logger.warning("classifier_result status=fallback error_type=%s latency_ms=%d timeout_ms=%d",
                       type(exc).__name__, int((time.monotonic() - started) * 1000), config.PAI_CLASSIFIER_TIMEOUT_MS)
        signals = fallback_signals()
        signals._fallback = True
        return signals
