"""API response and request bodies."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    id: int
    instance_key: str
    title: str
    kind: str
    inbox_kind: str | None
    programme_ref: str | None
    state: str
    blocked_reason: str | None
    due_at: datetime | None
    due_tz: str
    provisional: bool
    estimated: bool
    slack_days: int | None
    critical: bool
    citations: list[dict]


class PlanOut(BaseModel):
    plan_id: int
    revision: int
    status: str
    tasks: list[TaskOut]


class InboxOut(BaseModel):
    items: list[TaskOut]


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict = {}


class CompleteOut(BaseModel):
    completed: bool


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any
    quote: str
    url: str
    status: Literal["confirmed", "unconfirmed", "stale"]
    conflict_note: str | None = None


class ConfirmOut(BaseModel):
    revised_plans: list[int]


class UpgradeOut(BaseModel):
    revision: int
