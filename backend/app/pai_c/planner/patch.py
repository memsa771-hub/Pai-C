"""Atomic patch validation over a copy of the complete stored Truth Map."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Literal, Annotated
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from app.pai_c.deep.notebook_schema import CounselorNotebookData, Item, SourceItem, Rating
from app.pai_c.deep.notebook_sanitize import sanitize_notebook
from app.pai_c.deep.coverage import enforce_mirror_readiness
from app.pai_c.planner.view import PARTS


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class NewItem(Contract):
    key: str = Field(min_length=1)
    value: Any
    evidence: str = Field(min_length=1)
    kind: Literal["said", "shown", "document", "action"]
    confidence: Literal["low", "medium", "high"]
    level: Literal["claimed", "tried", "sustained", "proven"] | None = None
    category: Literal["self", "family", "peers", "media", "need", "other", "unknown"] | None = None
    vault_fact_ref: str | None = None


class Add(Contract):
    op: Literal["add"]
    part: Literal["said", "shown", "source", "self", "pressures.items"]
    item: NewItem


class UpdateFields(Contract):
    value: Any = None
    evidence: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] | None = None
    level: Literal["claimed", "tried", "sustained", "proven"] | None = None


class Update(Contract):
    op: Literal["update"]
    id: str
    fields: UpdateFields


class Confirm(Contract):
    op: Literal["confirm"]
    id: str
    evidence: str = Field(min_length=1)


class Retire(Contract):
    op: Literal["retire"]
    id: str
    reason: str = Field(min_length=1)


class UpsertPerson(Contract):
    op: Literal["upsert_person"]
    role: str = Field(min_length=1)
    wish: str
    concern: str
    evidence: str = Field(min_length=1)


class SetSure(Contract):
    op: Literal["set_sure"]
    score: int = Field(ge=0, le=10)
    reason: str
    would_raise: str
    evidence: str = Field(min_length=1)


class SetPrivate(Contract):
    op: Literal["set_private"]
    field: Literal["tensions", "identity_status", "decision_difficulties", "hypotheses", "open_questions", "private_notes", "engagement_style", "depth_mode"]
    value: Any


class SetCoverage(Contract):
    op: Literal["set_coverage"]
    part: Literal["said", "shown", "source", "pressures", "self", "sure"]
    value: bool


OPERATION = TypeAdapter(Annotated[Add | Update | Confirm | Retire | UpsertPerson | SetSure | SetPrivate | SetCoverage, Field(discriminator="op")])


class PatchRejected(ValueError):
    def __init__(self, index, error_type):
        self.index, self.error_type = index, error_type
        super().__init__(f"op_index={index} error_type={error_type}")


def apply_patch(notebook, operations, visible_ids, latest_student_text, *, now=None):
    if not isinstance(operations, list):
        raise PatchRejected(-1, "InvalidPatchShape")
    data = deepcopy(notebook.model_dump(mode="json"))
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    def items(part):
        return data["pressures"]["items"] if part == "pressures.items" else data[part]
    def find(item_id):
        if item_id not in visible_ids:
            raise ValueError("id not present in Planner view")
        matches = [row for part in PARTS for row in items(part) if row["id"] == item_id]
        if len(matches) != 1:
            raise ValueError("id must identify exactly one stored item")
        return matches[0]
    index = -1
    try:
        for index, raw in enumerate(operations):
            operation = OPERATION.validate_python(raw)
            if isinstance(operation, Add):
                entry = operation.item.model_dump(exclude_unset=True)
                if operation.part != "source" and "category" in entry:
                    raise ValueError("category is source-only")
                if operation.part == "source" and entry.get("category") is None:
                    entry.pop("category", None)
                entry.update(id=str(uuid4()), first_seen=stamp, last_confirmed=stamp)
                kind = SourceItem if operation.part == "source" else Item
                items(operation.part).append(kind.model_validate(entry).model_dump(mode="json"))
            elif isinstance(operation, Update):
                find(operation.id).update(**operation.fields.model_dump(exclude_unset=True), last_confirmed=stamp)
            elif isinstance(operation, Confirm):
                find(operation.id).update(evidence=operation.evidence, last_confirmed=stamp)
            elif isinstance(operation, Retire):
                find(operation.id)["status"] = "retired"
            elif isinstance(operation, UpsertPerson):
                people = data["pressures"]["people"]
                person = next((row for row in people if row["role"].casefold() == operation.role.casefold()), None)
                values = operation.model_dump(exclude={"op"})
                if person is None:
                    people.append({**values, "first_seen": stamp, "last_confirmed": stamp})
                else:
                    person.update(**values, last_confirmed=stamp)
            elif isinstance(operation, SetSure):
                if not re.search(r"(?<![\w.+-])" + str(operation.score) + r"(?![\w.]|\s*\.\d)", latest_student_text):
                    raise ValueError("rating not present in latest student message")
                sure = data["sure"]
                if sure["score"] is not None:
                    sure["history"].append(Rating.model_validate({key: sure[key] for key in ("score", "reason", "asked_at")}).model_dump(mode="json"))
                sure.update(score=operation.score, reason=operation.reason, would_raise=operation.would_raise, asked_at=stamp)
            elif isinstance(operation, SetPrivate):
                caps = {"hypotheses": 8, "tensions": 6, "decision_difficulties": 6, "open_questions": 3}
                if (operation.field in caps and isinstance(operation.value, list)
                        and len(operation.value) > caps[operation.field]):
                    raise ValueError("private list exceeds write cap")
                data[operation.field] = deepcopy(operation.value)
            elif isinstance(operation, SetCoverage):
                if operation.value:
                    if operation.part == "sure":
                        supported = data["sure"]["score"] is not None
                    elif operation.part == "pressures":
                        supported = any(row["status"] == "active" for row in items("pressures.items")) or bool(data["pressures"]["people"])
                    else:
                        supported = any(row["status"] == "active" for row in items(operation.part))
                    if not supported:
                        raise ValueError("coverage has no active evidence")
                data["coverage"][operation.part] = operation.value
            # Detect invalid intermediate ops before a later op can hide them.
            CounselorNotebookData.model_validate(data)
        validated = CounselorNotebookData.model_validate(data)
        cleaned, issues = sanitize_notebook(validated.model_dump(mode="json"))
        if issues:
            raise ValueError("patch required sanitization")
        return enforce_mirror_readiness(cleaned)
    except Exception as exc:
        raise PatchRejected(index, type(exc).__name__) from None
