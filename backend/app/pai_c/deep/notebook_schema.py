"""Typed private notebook contract from COUNSELOR_V3_PROMPTS.md section 0."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Source = Literal["reels", "friend", "family", "relative", "need", "own_experience", "unknown"]


class StatedGoal(Note):
    text: str = Field(min_length=1)
    source_of_goal: Source = "unknown"
    first_said_turn: int = Field(ge=1)


class Person(Note):
    current_situation: str = ""
    daily_life: str = ""
    location_context: str = ""


class Claim(Note):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence_level: Literal["claimed", "tried", "sustained", "proven"]
    evidence: str = Field(min_length=1)
    interest_source: Source = "unknown"
    probed: bool = False

    @field_validator("evidence")
    @classmethod
    def nonblank_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence is required")
        return value


class Trait(Note):
    trait: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]

    @field_validator("evidence")
    @classmethod
    def nonblank_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence is required")
        return value


class Driver(Note):
    driver: str = Field(min_length=1)
    weight: str = Field(min_length=1)
    evidence: str = Field(min_length=1)

    @field_validator("evidence")
    @classmethod
    def nonblank_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence is required")
        return value


class FamilyMember(Note):
    wish: str = ""
    underlying_concern: str = ""


class Family(Note):
    father: FamilyMember = Field(default_factory=FamilyMember)
    mother: FamilyMember = Field(default_factory=FamilyMember)
    others: str = ""
    pressure_level: str = ""


class Constraint(Note):
    type: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    hard: bool


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
    person: bool = False
    education: bool = False
    claims_probed: bool = False
    proven_interests: bool = False
    family: bool = False
    real_why: bool = False
    constraints: bool = False
    goal_tested: bool = False


class GoalHistory(Note):
    goal: str = Field(min_length=1)
    source: Source = "unknown"
    session: int = Field(ge=1)


class CounselorNotebookData(Note):
    stated_goal: StatedGoal | None = None
    person: Person = Field(default_factory=Person)
    claims: list[Claim] = Field(default_factory=list)
    strengths: list[Trait] = Field(default_factory=list)
    growth_areas: list[Trait] = Field(default_factory=list)
    drivers: list[Driver] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    family: Family = Field(default_factory=Family)
    constraints: list[Constraint] = Field(default_factory=list)
    learning_style: str = ""
    work_preferences: str = ""
    emotional_notes: str = ""
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    mirror_ready: bool = False
    mirror_blockers: list[str] = Field(default_factory=list)
    engagement_style: Literal["open", "task_seeker", "short_answers", "decided", "impatient", "parent_proxy", "goal_switcher"] = "open"
    depth_mode: Literal["full", "focused", "light"] = "full"
    chapter: Literal["discovery", "coach", "next_chapter"] = "discovery"
    goal_history: list[GoalHistory] = Field(default_factory=list)
    coach: dict = Field(default_factory=dict)

    @field_validator("coach")
    @classmethod
    def defer_coach(cls, value: dict) -> dict:
        return {}
