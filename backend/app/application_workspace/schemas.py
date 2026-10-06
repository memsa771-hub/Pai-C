"""Validated API inputs for student-managed application plans."""
from typing import Literal

from pydantic import AwareDatetime, AnyHttpUrl, BaseModel, Field, field_validator

class InstitutionInput(BaseModel):
    network: str
    name: str = Field(min_length=2, max_length=240)
    country_code: str = Field(pattern=r"^[A-Za-z]{2}$")
    city: str | None = Field(default=None, max_length=160)
    website_url: AnyHttpUrl | None = None

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Institution name is required")
        return value


class NetworkInput(BaseModel):
    network: str


class PlanInput(BaseModel):
    network: str
    institution_id: str
    program_name: str | None = Field(default=None, max_length=240)
    intake: str | None = Field(default=None, max_length=120)
    route: str | None = Field(default=None, max_length=120)
    deadline_at: AwareDatetime | None = None
    application_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=5000)


class PlanUpdate(BaseModel):
    network: str
    program_name: str | None = Field(default=None, max_length=240)
    intake: str | None = Field(default=None, max_length=120)
    route: str | None = Field(default=None, max_length=120)
    status: Literal["planning", "preparing", "ready", "submitted", "decision", "withdrawn"] | None = None
    deadline_at: AwareDatetime | None = None
    application_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=5000)
    submission_reference: str | None = Field(default=None, max_length=240)


class RequirementInput(BaseModel):
    network: str
    label: str = Field(min_length=1, max_length=240)
    kind: str = Field(default="other", min_length=1, max_length=80)
    due_at: AwareDatetime | None = None
    source_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("label", "kind")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class RequirementUpdate(BaseModel):
    network: str
    label: str | None = Field(default=None, min_length=1, max_length=240)
    kind: str | None = Field(default=None, min_length=1, max_length=80)
    status: Literal["todo", "in_progress", "done", "not_applicable"] | None = None
    due_at: AwareDatetime | None = None
    source_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=2000)
    task_id: str | None = None
    file_id: str | None = None


class RequirementTaskInput(BaseModel):
    network: str
    workflow_id: str | None = None


class ReviewRoutineInput(BaseModel):
    network: str
    name: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=1000)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    days: list[int] | None = None
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("days")
    @classmethod
    def valid_days(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (not value or any(day < 0 or day > 6 for day in value)):
            raise ValueError("Choose valid weekdays or leave empty for daily")
        return sorted(set(value)) if value else None


