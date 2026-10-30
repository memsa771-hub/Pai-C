"""Atomic patch validation over a copy of the complete stored Truth Map."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Literal, Annotated
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from app.pai_c.deep.notebook_schema import CounselorNotebookData, Item, SourceItem, Rating
from app.pai_c.deep.notebook_sanitize import sanitize_notebook
from app.pai_c.deep.coverage import enforce_mirror_readiness, requirements
from app.pai_c.understanding.data import load_policy, at_path


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
    capability_status: Literal["demonstrated", "emerging", "untested", "development_need", "blocked"] | None = None


class Add(Contract):
    op: Literal["add"]
    part: Literal["said", "shown", "source", "self", "pressures.items", "world.social", "world.daily_life", "world.responsibilities", "world.education_story"]
    item: NewItem


class UpdateFields(Contract):
    value: Any = None
    evidence: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] | None = None
    level: Literal["claimed", "tried", "sustained", "proven"] | None = None
    capability_status: Literal["demonstrated", "emerging", "untested", "development_need", "blocked"] | None = None


class PersonFields(Contract):
    evidence: str = Field(min_length=1)
    role: str = Field(min_length=1)
    relation: Literal["parent", "sibling", "relative", "partner", "friend", "mentor", "other"] = "other"
    occupation: str | None = None
    relationship_note: str = ""
    wish: str = ""
    worry: str = ""
    influence: Literal["low", "medium", "high", "unknown"] = "unknown"
    supportive: bool | None = None


class PersonUpdate(PersonFields):
    role: str | None = Field(default=None, min_length=1)


class Update(Contract):
    op: Literal["update"]
    id: str
    fields: UpdateFields | PersonUpdate


class Confirm(Contract):
    op: Literal["confirm"]
    id: str
    evidence: str = Field(min_length=1)


class Retire(Contract):
    op: Literal["retire"]
    id: str
    reason: str = Field(min_length=1)


class UpsertPerson(PersonFields):
    op: Literal["upsert_person"]


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
    """`reason` is why the op failed, in schema words only (field paths, error
    types, this module's fixed messages): it goes back to the planner as
    correction feedback and into the log, so it never carries student text."""
    def __init__(self, index, error_type, reason=""):
        self.index, self.error_type, self.reason = index, error_type, reason
        super().__init__(f"op_index={index} error_type={error_type}" + (f" reason={reason}" if reason else ""))


def rejection_reason(exc) -> str:
    """A pydantic error reduced to field paths and error types (never the
    input); this module's own ValueErrors are fixed strings; anything else
    gives no reason beyond its type."""
    if isinstance(exc, ValidationError):
        return "; ".join(".".join(str(part) for part in error["loc"]) + ": " + error["type"]
                         for error in exc.errors()[:6])
    if type(exc) is ValueError:
        return str(exc)
    return ""


def apply_patch(notebook, operations, visible_ids, latest_student_text, *, now=None, evidence_refs=()):
    if not isinstance(operations, list):
        raise PatchRejected(-1, "InvalidPatchShape")
    data = deepcopy(notebook.model_dump(mode="json"))
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    parts = (*load_policy()["item_paths"], load_policy()["person_path"])
    added_people = set()
    def items(part):
        return at_path(data, part)
    def find(item_id):
        if item_id not in visible_ids:
            raise ValueError("id not present in Planner view")
        matches = [row for part in parts for row in items(part) if row["id"] == item_id]
        if len(matches) != 1:
            raise ValueError("id must identify exactly one stored item")
        return matches[0]
    index = -1
    try:
        for index, raw in enumerate(operations):
            operation = OPERATION.validate_python(raw)
            if isinstance(operation, Add):
                entry = operation.item.model_dump(exclude_unset=True)
                # A model cannot promote a report into independent evidence.
                if (entry.get("kind") != "said" or entry.get("capability_status") == "demonstrated" or entry.get("level") == "proven") and entry.get("vault_fact_ref") not in evidence_refs:
                    raise ValueError("independent evidence requires a supported profile reference")
                if operation.part != "source" and "category" in entry:
                    raise ValueError("category is source-only")
                if operation.part == "source" and entry.get("category") is None:
                    entry.pop("category", None)
                entry.update(id=str(uuid4()), first_seen=stamp, last_confirmed=stamp)
                kind = SourceItem if operation.part == "source" else Item
                items(operation.part).append(kind.model_validate(entry).model_dump(mode="json"))
            elif isinstance(operation, Update):
                target = find(operation.id)
                if (getattr(operation.fields, "capability_status", None) == "demonstrated" or getattr(operation.fields, "level", None) == "proven") and target.get("vault_fact_ref") not in evidence_refs:
                    raise ValueError("demonstrated capability requires a supported profile reference")
                target.update(**operation.fields.model_dump(exclude_unset=True), last_confirmed=stamp)
            elif isinstance(operation, Confirm):
                find(operation.id).update(evidence=operation.evidence, last_confirmed=stamp)
            elif isinstance(operation, Retire):
                find(operation.id)["status"] = "retired"
            elif isinstance(operation, UpsertPerson):
                people = items(load_policy()["person_path"])
                person = next((row for row in people if row["role"].casefold() == operation.role.casefold()), None)
                values = operation.model_dump(exclude={"op"}, exclude_unset=True)
                if person is None:
                    person_id = str(uuid4())
                    added_people.add(person_id)
                    people.append({**values, "id": person_id, "first_seen": stamp, "last_confirmed": stamp})
                else:
                    if person["id"] not in visible_ids and person["id"] not in added_people:
                        raise ValueError("person not present in Planner view")
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
                        supported = any(row["status"] == "active" for row in items("pressures.items")) or any(row.get("status", "active") == "active" for row in items(load_policy()["person_path"]))
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
        # The Planner writes coverage, not mirror_ready. Recompute readiness so
        # new workspaces can become reviewable and retired evidence cannot keep
        # an old readiness flag alive indefinitely.
        support = {part: any(row.status == "active" for row in getattr(cleaned, part))
                   for part in ("said", "shown", "source", "self")}
        support["pressures"] = any(row.status == "active" for row in cleaned.pressures.items)
        support["sure"] = cleaned.sure.score is not None
        ready = all(getattr(cleaned.coverage, key) and support[key]
                    for key in requirements()[cleaned.depth_mode])
        return enforce_mirror_readiness(cleaned.model_copy(update={"mirror_ready": ready}))
    except Exception as exc:
        raise PatchRejected(index, type(exc).__name__, rejection_reason(exc)) from None
