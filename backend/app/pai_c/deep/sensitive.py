"""One background sensitivity decision for all changed notebook entries."""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from app.config import config
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.deep.prompts import load_prompt
from app.inference.gateway import complete as chat_completion, resolve_model

logger = logging.getLogger(__name__)
ChangedEntry = dict[str, str]
SensitiveChecker = Callable[[list[ChangedEntry]], Awaitable[set[str]]]
_DROP = object()


@dataclass(frozen=True)
class SensitiveRemoval:
    path: str
    reason: str = "sensitive_content"


async def model_sensitive_checker(entries: list[ChangedEntry]) -> set[str]:
    """One model call for the batch; require one decision for every submitted path."""
    if not entries:
        return set()
    raw = await chat_completion(role="sensitive",
        api_key=config.PAI_API_KEY, model=resolve_model("sensitive"),
        messages=[{"role": "user", "content": json.dumps(entries, ensure_ascii=False)}],
        system_prompt=load_prompt("sensitive_check"),
        response_format={"type": "json_object"},
        max_tokens=config.PAI_COUNSELOR_SENSITIVE_CHECK_MAX_TOKENS,
        reasoning_effort=config.PAI_SENSITIVE_CHECK_REASONING_EFFORT,
        base_url=config.PAI_BASE_URL,
    )
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("sensitive check returned invalid JSON") from exc
    decisions = answer.get("decisions") if isinstance(answer, dict) else None
    if not isinstance(decisions, list):
        raise ValueError("sensitive check returned no decisions")
    expected = {entry["path"] for entry in entries}
    found: set[str] = set()
    flagged: set[str] = set()
    for item in decisions:
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or type(item.get("sensitive")) is not bool
                or item["path"] not in expected or item["path"] in found):
            raise ValueError("sensitive check returned an invalid path or decision")
        found.add(item["path"])
        if item["sensitive"]:
            flagged.add(item["path"])
    if found != expected:
        raise ValueError("sensitive check omitted changed entries")
    return flagged


def _entry_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if not isinstance(value, str) else value


def _default(field) -> Any:
    if field.default_factory is not None:
        return field.default_factory()
    return field.default if field.default is not PydanticUndefined else _DROP


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) in (UnionType, Union):
        return next((part for part in get_args(annotation)
                     if isinstance(part, type) and issubclass(part, BaseModel)), None)
    return None


def _changed_entries(old: dict, new: dict, model: type[BaseModel], path: str = "") -> list[ChangedEntry]:
    entries: list[ChangedEntry] = []
    for name, field in model.model_fields.items():
        if field.exclude:
            continue
        value, prior = new.get(name), old.get(name)
        if value == prior or value is None:
            continue
        field_path = f"{path}.{name}" if path else name
        if isinstance(value, list):
            previous_entries = prior if isinstance(prior, list) else []
            entries.extend({"path": f"{field_path}[{index}]", "text": _entry_text(item)}
                           for index, item in enumerate(value)
                           if item not in previous_entries)
        elif isinstance(value, dict) and (nested_model := _nested_model(field.annotation)):
            entries.extend(_changed_entries(prior or {}, value, nested_model, field_path))
        elif isinstance(value, str) and value and get_origin(field.annotation) is not Literal:
            entries.append({"path": field_path, "text": value})
    return entries


def _remove_flagged(new: dict, model: type[BaseModel], flagged: set[str], path: str = "") -> dict | object:
    cleaned = dict(new)
    for name, field in model.model_fields.items():
        if field.exclude:
            continue
        value = new.get(name)
        field_path = f"{path}.{name}" if path else name
        if isinstance(value, list):
            cleaned[name] = [item for index, item in enumerate(value)
                             if f"{field_path}[{index}]" not in flagged]
        elif isinstance(value, dict) and (nested_model := _nested_model(field.annotation)):
            nested = _remove_flagged(value, nested_model, flagged, field_path)
            cleaned[name] = _default(field) if nested is _DROP else nested
        elif field_path in flagged:
            replacement = _default(field)
            if replacement is _DROP:
                return _DROP
            cleaned[name] = replacement
    return cleaned


async def filter_sensitive_changes(
    previous: CounselorNotebookData,
    candidate: CounselorNotebookData,
    checker: SensitiveChecker = model_sensitive_checker,
) -> tuple[CounselorNotebookData, list[SensitiveRemoval]]:
    """Batch changed free text once; never partially save an incomplete decision."""
    old = previous.model_dump(mode="json")
    new = candidate.model_dump(mode="json")
    entries = _changed_entries(old, new, CounselorNotebookData)
    flagged = await checker(entries) if entries else set()
    expected = {entry["path"] for entry in entries}
    if not isinstance(flagged, set) or not flagged <= expected:
        raise ValueError("sensitive check returned an invalid selection")
    removals = [SensitiveRemoval(entry["path"]) for entry in entries
                if entry["path"] in flagged]
    for item in removals:
        logger.info("notebook_sensitive path=%s reason=%s", item.path, item.reason)
    output = _remove_flagged(new, CounselorNotebookData, flagged)
    if output is _DROP:
        raise ValueError("sensitive check could not clean notebook")
    return CounselorNotebookData.model_validate(output), removals


async def check_notebook_before_mirror(workspace_id: str, *, db=None,
                                       checker: SensitiveChecker | None = None):
    """Batch the whole notebook once before PR 6 generates a mirror.

    Return (snapshot, removals). Removed content is persisted with optimistic
    locking, and readiness is cleared so discovery can repair the gaps. A
    failed check or concurrent update raises; callers must not generate a
    mirror from an unchecked or stale snapshot. No read transaction is kept
    open during the model call.
    """
    from app.pai_c.deep.notebook import NotebookVersionConflict
    from app.pai_c.memory import MemoryService
    from app.inference.gateway import token_usage_turn
    from app.database import new_session

    if db is None:
        with new_session() as session:
            return await check_notebook_before_mirror(workspace_id, db=session, checker=checker)
    service = MemoryService(db)
    previous = service.truth_map(workspace_id)
    db.rollback()
    with token_usage_turn(previous.last_event_id):
        clean, removals = await filter_sensitive_changes(
            CounselorNotebookData(), previous.notebook,
            checker=checker or model_sensitive_checker)
    current = service.truth_map(workspace_id)
    if current.version != previous.version:
        db.rollback()
        raise NotebookVersionConflict("notebook changed during pre-mirror check")
    if not removals:
        db.rollback()
        return previous, []
    clean = clean.model_copy(update={"mirror_ready": False, "mirror_blockers": [*clean.mirror_blockers, "Removed sensitive entries require further discovery"]})
    snapshot, _ = service.apply_truth_map(workspace_id, clean, previous.last_event_id,
                                expected_version=previous.version)
    return snapshot, removals
