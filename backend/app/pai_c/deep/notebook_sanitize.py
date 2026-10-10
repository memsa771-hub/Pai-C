"""Loss-minimizing, auditable cleanup before strict notebook validation."""

import logging
import re
from dataclasses import dataclass
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import PydanticUndefined

from app.pai_c.deep.notebook_schema import CounselorNotebookData

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SanitizationIssue:
    path: str
    action: str
    reason: str | None = None


def _record(issues: list[SanitizationIssue], path: str, action: str, *,
            reason: str | None = None) -> None:
    issue = SanitizationIssue(path, action, reason)
    issues.append(issue)
    # Never log the student text or ValidationError (whose repr includes input).
    logger.info("notebook_sanitize path=%s action=%s reason=%s", path, action, reason)


def _model_type(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) in (UnionType, Union):
        return next((kind for kind in get_args(annotation)
                     if isinstance(kind, type) and issubclass(kind, BaseModel)), None)
    return None


def _has_default(field: Any) -> bool:
    return field.default is not PydanticUndefined or field.default_factory is not None


def _default(field: Any) -> Any:
    if field.default_factory is not None:
        return field.default_factory()
    return field.default


def _failure_reason(exc: ValidationError) -> str:
    return ("missing_evidence" if any(
        "evidence" in str(part) for error in exc.errors(include_input=False)
        for part in error["loc"]
    ) else "invalid_value")


def _clean_model(value: Any, model: type[BaseModel], path: str,
                 issues: list[SanitizationIssue]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        field = model.model_fields.get(key)
        if field is None:
            safe_key = key if isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", key) else "<unknown>"
            field_path = f"{path}.{safe_key}" if path else safe_key
            _record(issues, field_path, "dropped_unknown_field")
            continue
        field_path = f"{path}.{key}" if path else key
        if key == "coach" and model is CounselorNotebookData:
            if item != {}:
                _record(issues, field_path, "repaired", reason="coach_deferred")
            cleaned[key] = {}
            continue
        annotation = field.annotation
        origin = get_origin(annotation)
        nested = _model_type(annotation)
        if origin is list:
            if not isinstance(item, list):
                _record(issues, field_path, "dropped_field", reason="invalid_list")
                continue
            entry_type = get_args(annotation)[0]
            entry_model = _model_type(entry_type)
            kept: list[Any] = []
            for index, entry in enumerate(item):
                entry_path = f"{field_path}[{index}]"
                try:
                    candidate = (_clean_model(entry, entry_model, entry_path, issues)
                                 if entry_model else entry)
                    kept.append(TypeAdapter(entry_type).validate_python(candidate))
                except (ValidationError, ValueError) as exc:
                    reason = _failure_reason(exc) if isinstance(exc, ValidationError) else "invalid_value"
                    _record(issues, entry_path, "dropped_entry", reason=reason)
            cleaned[key] = kept
            continue
        try:
            candidate = (_clean_model(item, nested, field_path, issues)
                         if nested and item is not None else item)
            cleaned[key] = TypeAdapter(annotation).validate_python(candidate)
        except (ValidationError, ValueError) as exc:
            reason = _failure_reason(exc) if isinstance(exc, ValidationError) else "invalid_value"
            if _has_default(field):
                cleaned[key] = _default(field)
                _record(issues, field_path, "repaired", reason=reason)
            else:
                _record(issues, field_path, "dropped_field", reason=reason)
    return cleaned


def sanitize_notebook(raw: dict[str, Any]) -> tuple[CounselorNotebookData, list[SanitizationIssue]]:
    if "legacy_v1" in raw:
        raise ValueError("legacy_v1 is read-only")
    CounselorNotebookData.reject_v1(raw)
    issues: list[SanitizationIssue] = []
    cleaned = _clean_model(raw, CounselorNotebookData, "", issues)
    # The lenient pass removes bad entries; this strict check remains the
    # storage boundary and prevents malformed nested data from being saved.
    return CounselorNotebookData.model_validate(cleaned), issues
