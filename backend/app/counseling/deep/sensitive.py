"""Deferred background check for changed notebook entries.

The Analyst will call this before NotebookService.apply in PR 4. Storage does
not invoke a model or make content judgments on its own.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from app.config import config
from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.counseling.deep.prompts import load_prompt
from app.inference.client import chat_completion

logger = logging.getLogger(__name__)
SensitiveChecker = Callable[[str], Awaitable[bool]]
_DROP = object()


@dataclass(frozen=True)
class SensitiveRemoval:
    path: str
    reason: str = "sensitive_content"


async def model_sensitive_checker(text: str) -> bool:
    """One small model call for one changed entry; fail if the answer is unusable."""
    raw = await chat_completion(
        api_key=config.PAI_API_KEY, model=config.PAI_COUNSELOR_MODEL,
        messages=[{"role": "user", "content": text}],
        system_prompt=load_prompt("sensitive_check"),
        response_format={"type": "json_object"},
        max_tokens=config.PAI_COUNSELOR_SENSITIVE_CHECK_MAX_TOKENS,
        reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
        base_url=config.PAI_BASE_URL,
    )
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("sensitive check returned invalid JSON") from exc
    if not isinstance(answer, dict) or type(answer.get("sensitive")) is not bool:
        raise ValueError("sensitive check returned invalid decision")
    return answer["sensitive"]


def _entry_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if not isinstance(value, str) else value


def _default(field) -> Any:
    if field.default_factory is not None:
        return field.default_factory()
    return field.default if field.default is not PydanticUndefined else _DROP


def _prior_list_entry(old: list, item: Any, index: int) -> Any:
    if isinstance(item, dict) and "id" in item:
        return next((previous for previous in old if isinstance(previous, dict)
                     and previous.get("id") == item["id"]), None)
    return old[index] if index < len(old) else None


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) in (UnionType, Union):
        return next((part for part in get_args(annotation)
                     if isinstance(part, type) and issubclass(part, BaseModel)), None)
    return None


async def filter_sensitive_changes(
    previous: CounselorNotebookData,
    candidate: CounselorNotebookData,
    checker: SensitiveChecker = model_sensitive_checker,
) -> tuple[CounselorNotebookData, list[SensitiveRemoval]]:
    """Check only changed free-text entries; never partially save on check failure."""
    removals: list[SensitiveRemoval] = []

    async def visit(old: dict, new: dict, model: type[BaseModel], path: str) -> dict | object:
        cleaned = dict(new)
        for name, field in model.model_fields.items():
            value = new.get(name)
            prior = old.get(name)
            if value == prior or value is None:
                continue
            field_path = f"{path}.{name}" if path else name
            if isinstance(value, list):
                kept = []
                previous_entries = prior if isinstance(prior, list) else []
                for index, item in enumerate(value):
                    old_item = _prior_list_entry(previous_entries, item, index)
                    if item != old_item and await checker(_entry_text(item)):
                        item_path = f"{field_path}[{index}]"
                        removals.append(SensitiveRemoval(item_path))
                        logger.info("notebook_sensitive path=%s reason=sensitive_content", item_path)
                    else:
                        kept.append(item)
                cleaned[name] = kept
            elif isinstance(value, dict) and (nested_model := _nested_model(field.annotation)):
                nested = await visit(prior or {}, value, nested_model, field_path)
                cleaned[name] = _default(field) if nested is _DROP else nested
            elif isinstance(value, str) and get_origin(field.annotation) is None:
                if value and await checker(value):
                    removals.append(SensitiveRemoval(field_path))
                    logger.info("notebook_sensitive path=%s reason=sensitive_content", field_path)
                    replacement = _default(field)
                    if replacement is _DROP:
                        return _DROP
                    cleaned[name] = replacement
        return cleaned

    output = await visit(previous.model_dump(mode="json"), candidate.model_dump(mode="json"),
                         CounselorNotebookData, "")
    if output is _DROP:
        raise ValueError("sensitive check could not clean notebook")
    return CounselorNotebookData.model_validate(output), removals
