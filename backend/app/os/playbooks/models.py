"""Playbook schema: a versioned route template, validated at load time (spec §4.1)."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Citation(_Model):
    source: str
    url: AnyHttpUrl


class Dependency(_Model):
    key: str
    hard: bool = True


class Condition(_Model):
    fact: str
    in_: list[str] | None = Field(None, alias="in")
    present: bool | None = None

    @model_validator(mode="after")
    def _one_test(self) -> "Condition":
        if (self.in_ is None) == (self.present is None):
            raise ValueError("condition needs exactly one of 'in' or 'present'")
        return self


class Anchor(_Model):
    fact: str


class LeadTime(_Model):
    days: int | None = Field(None, ge=0)
    constant: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "LeadTime":
        if (self.days is None) == (self.constant is None):
            raise ValueError("lead_time needs exactly one of 'days' or 'constant'")
        return self


class TaskTemplate(_Model):
    template_key: str
    task_type: str
    title: str
    kind: Literal["work", "student"]
    inbox_kind: Literal["provide", "approve", "act", "choose"] | None = None
    depends_on: list[Dependency] = []
    fan_out: Literal["none", "programme"] = "none"
    condition: Condition | None = None
    anchor: Anchor | None = None
    lead_time: LeadTime | None = None
    duration_days: int = Field(1, ge=0)
    duration_constant: str | None = None
    fallback: Literal["skip", "student"] = "skip"
    protected: bool = False
    citations: list[Citation] = []
    citation_from_fact: str | None = None

    @model_validator(mode="after")
    def _inbox_kind_matches_kind(self) -> "TaskTemplate":
        if self.kind == "student" and self.inbox_kind is None:
            raise ValueError(f"student task needs inbox_kind ({self.template_key})")
        if self.kind == "work" and self.inbox_kind is not None:
            raise ValueError(f"work task cannot have inbox_kind ({self.template_key})")
        return self


class Constant(_Model):
    value: int | str
    citations: list[Citation] = []
    estimate: bool = False


class Route(_Model):
    origin: str
    destination: str
    level: str


class Playbook(_Model):
    key: str
    version: int = Field(ge=1)
    route: Route
    default_timezone: str
    require_citations: bool = False
    constants: dict[str, Constant] = {}
    tasks: list[TaskTemplate]

    @field_validator("default_timezone")
    @classmethod
    def _known_timezone(cls, tz: str) -> str:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone '{tz}'") from None
        return tz

    @model_validator(mode="after")
    def _references_resolve(self) -> "Playbook":
        keys = [t.template_key for t in self.tasks]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"duplicate template_key {dupes}")
        known = set(keys)
        for t in self.tasks:
            for dep in t.depends_on:
                if dep.key not in known:
                    raise ValueError(f"unknown dependency '{dep.key}' in {t.template_key}")
            for name in (t.lead_time.constant if t.lead_time else None, t.duration_constant):
                if name is not None and name not in self.constants:
                    raise ValueError(f"unknown constant '{name}' in {t.template_key}")
            if self.require_citations and not t.citations and not t.citation_from_fact:
                raise ValueError(f"task {t.template_key} needs a citation (require_citations is on)")
        return self

    def task(self, template_key: str) -> TaskTemplate:
        return next(t for t in self.tasks if t.template_key == template_key)
