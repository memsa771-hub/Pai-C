"""Replan operations (Slice 7 spec S7-D4, D5, D7): one typed union, shared by the rules and the Supervisor. Each
carries a one-line reason shown to the student. Add, skip, cancel and reorder become plan overrides that the
compiler applies on every compile; the others act through the kernel, the inbox or the support inbox."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.os.replan.store import Override

MAX_OPS = 10  # per wake (S7-D9)
BIG_ADD_DAYS = 1  # adding more student work than this needs the student's acceptance (S7-D7)


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str = Field(min_length=1, max_length=200)


class AddTask(_Op):
    op: Literal["add_task"] = "add_task"
    template_key: str
    programme_ref: str | None = None


class SkipTask(_Op):
    op: Literal["skip_task"] = "skip_task"
    instance_key: str


class CancelTask(_Op):
    op: Literal["cancel_task"] = "cancel_task"
    instance_key: str


class CancelProgramme(_Op):
    op: Literal["cancel_programme"] = "cancel_programme"
    programme_ref: str


class Reprioritise(_Op):
    op: Literal["reprioritise"] = "reprioritise"
    instance_key: str  # this step goes first...
    before: str  # ...before this one


class SwapProgramme(_Op):
    op: Literal["swap_programme"] = "swap_programme"
    out_ref: str
    in_ref: str


class RequestFromStudent(_Op):
    op: Literal["request_from_student"] = "request_from_student"
    instance_key: str
    message: str = Field(min_length=1, max_length=300)


class Escalate(_Op):
    op: Literal["escalate"] = "escalate"


class UpgradePlaybook(_Op):
    """Rules only (never the Supervisor): move the plan to a newer playbook version, always big (invariant 10)."""

    op: Literal["upgrade_playbook"] = "upgrade_playbook"
    version: int = Field(ge=1)


Op = Annotated[Union[AddTask, SkipTask, CancelTask, CancelProgramme, Reprioritise, SwapProgramme, RequestFromStudent,
                     Escalate, UpgradePlaybook], Field(discriminator="op")]
Ops = Annotated[list[Op], Field(max_length=MAX_OPS)]


@dataclass(frozen=True)
class TaskRow:
    """One task of the running plan, as the rules, the checks and the Supervisor see it."""

    instance_key: str
    template_key: str
    programme_ref: str | None
    state: str
    kind: str
    critical: bool
    protected: bool
    latest_finish: datetime | None
    slack_days: int | None
    duration_days: int
    depends_on: tuple[tuple[str, bool], ...]
    task_type: str = ""  # e.g. the fact check's type (Slice 9a Task 11: a removed programme's checks go with it)


def is_big(op: Op, tasks: Mapping[str, TaskRow], playbook) -> bool:
    """Big changes need the student's acceptance (S7-D7)."""
    if isinstance(op, (SwapProgramme, CancelProgramme, UpgradePlaybook)):
        return True
    if isinstance(op, (CancelTask, SkipTask)):
        t = tasks.get(op.instance_key)
        return t is not None and t.critical
    if isinstance(op, AddTask):
        base = op.template_key if op.programme_ref is None else f"{op.template_key}@{op.programme_ref}"
        if base in tasks:  # doing a step of the plan again (e.g. approving a changed file, S7-D11): small
            return False
        tmpl = next((t for t in playbook.tasks if t.template_key == op.template_key), None)
        if tmpl is None or tmpl.kind != "student":
            return False
        days = (int(playbook.constants[tmpl.duration_constant].value) if tmpl.duration_constant
                else tmpl.duration_days)
        return days > BIG_ADD_DAYS
    return False


def to_overrides(op: Op) -> list[Override]:
    """The plan overrides an operation writes (S7-D5); empty for operations that act elsewhere."""
    if isinstance(op, AddTask):
        return [Override("add", op.template_key, {"programme_ref": op.programme_ref})]
    if isinstance(op, SkipTask):
        return [Override("skip", op.instance_key, {})]
    if isinstance(op, CancelTask):
        return [Override("cancel", op.instance_key, {})]
    if isinstance(op, CancelProgramme):
        return [Override("cancel_programme", op.programme_ref, {})]
    if isinstance(op, Reprioritise):
        return [Override("reprioritise", op.instance_key, {"before": op.before})]
    return []
