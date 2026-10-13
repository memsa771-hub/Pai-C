"""Strict Truth Map v2 contract. Objective records remain in the Vault."""

from copy import deepcopy
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Source = Literal["reels", "friend", "family", "relative", "need", "own_experience", "unknown"]


class Item(Note):
    id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: Any
    evidence: str = Field(min_length=1)
    kind: Literal["said", "shown", "document", "action"]
    confidence: Literal["low", "medium", "high"] = "low"
    level: Literal["claimed", "tried", "sustained", "proven"] | None = None
    first_seen: datetime
    last_confirmed: datetime
    status: Literal["active", "retired"] = "active"
    vault_fact_ref: str | None = None

    @model_validator(mode="after")
    def objective_reference_required(self):
        # Structural field families, not matching conversation text or topics.
        if self.key.split(".", 1)[0] in {"education", "tests", "documents", "money", "places"} and not self.vault_fact_ref:
            raise ValueError("objective facts require vault_fact_ref")
        return self


class SourceItem(Item):
    category: Literal["self", "family", "peers", "media", "need", "other", "unknown"] = "unknown"


class PersonPressure(Note):
    role: str = Field(min_length=1)
    wish: str = ""
    concern: str = ""
    evidence: str = Field(min_length=1)
    first_seen: datetime
    last_confirmed: datetime


class Pressures(Note):
    items: list[Item] = Field(default_factory=list)
    people: list[PersonPressure] = Field(default_factory=list)


class Rating(Note):
    score: int | None = Field(default=None, ge=0, le=10, strict=True)
    reason: str = ""
    asked_at: datetime | None = None


class Sure(Rating):
    would_raise: str = ""
    history: list[Rating] = Field(default_factory=list)


class Tension(Note):
    between: list[str]
    evidence: str = Field(min_length=1)
    status: str = Field(min_length=1)


class IdentityStatus(Note):
    exploration: str = ""
    commitment: str = ""
    label: Literal["achieved", "foreclosed", "moratorium", "diffused", "unknown"] = "unknown"


class DecisionDifficulty(Note):
    category: Literal["readiness", "information", "inconsistent"]
    evidence: str = Field(min_length=1)
    status: str = Field(min_length=1)


class Hypothesis(Note):
    text: str = Field(min_length=1)
    status: Literal["supported", "open", "rejected"]
    evidence_for: str = ""
    evidence_against: str = ""

    @field_validator("evidence_for", "evidence_against")
    @classmethod
    def trim_evidence(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def has_evidence(self):
        if not self.evidence_for and not self.evidence_against:
            raise ValueError("hypothesis evidence is required")
        return self


class OpenQuestion(Note):
    priority: int = Field(ge=1)
    area: str = Field(min_length=1)
    question_intent: str = Field(min_length=1)


class Coverage(Note):
    said: bool = False
    shown: bool = False
    source: bool = False
    pressures: bool = False
    self: bool = False
    sure: bool = False


class GoalHistory(Note):
    goal: str = Field(min_length=1)
    source: Source = "unknown"
    session: int = Field(ge=1)


class CounselorNotebookData(Note):
    schema_version: Literal[2] = 2
    said: list[Item] = Field(default_factory=list)
    shown: list[Item] = Field(default_factory=list)
    source: list[SourceItem] = Field(default_factory=list)
    pressures: Pressures = Field(default_factory=Pressures)
    self: list[Item] = Field(default_factory=list)
    sure: Sure = Field(default_factory=Sure)
    tensions: list[Tension] = Field(default_factory=list)
    identity_status: IdentityStatus = Field(default_factory=IdentityStatus)
    decision_difficulties: list[DecisionDifficulty] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    private_notes: str = ""
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    mirror_ready: bool = False
    mirror_blockers: list[str] = Field(default_factory=list)
    engagement_style: Literal["open", "task_seeker", "short_answers", "decided", "impatient", "parent_proxy", "goal_switcher"] = "open"
    depth_mode: Literal["full", "focused", "light"] = "full"
    chapter: Literal["discovery", "coach", "next_chapter"] = "discovery"
    goal_history: list[GoalHistory] = Field(default_factory=list)
    legacy_v1: dict[str, Any] | None = Field(default=None, exclude=True, repr=False, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def reject_v1(cls, value):
        if isinstance(value, dict) and (value.get("schema_version", 2) != 2 or
                any(key in value for key in ("claims", "person", "stated_goal", "strengths", "growth_areas", "drivers", "values", "family", "constraints", "learning_style", "work_preferences", "emotional_notes", "coach"))):
            raise ValueError("Truth Map v1 must be migrated before use")
        return value

    @field_validator("legacy_v1")
    @classmethod
    def isolate_archive(cls, value):
        return deepcopy(value)

    @classmethod
    def analyst_schema(cls):
        schema = cls.model_json_schema()
        schema["properties"].pop("legacy_v1", None)
        return schema

    def storage_data(self):
        data = self.model_dump(mode="json")
        if self.legacy_v1 is not None:
            data["legacy_v1"] = deepcopy(self.legacy_v1)
        return data

    def export_data(self):
        return {**self.model_dump(mode="json"), "has_legacy_v1": self.legacy_v1 is not None}
