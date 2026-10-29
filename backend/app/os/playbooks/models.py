"""Playbook schema: a versioned route template, validated at load time (spec §4.1)."""

from string import Formatter
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.os.eligibility.rules import EligibilityRules, SelfServe


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


NOTE_FIELDS = frozenset({"date", "due", "days", "weeks"})


def placeholders(note: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(note) if name is not None}


class Anchor(_Model):
    """The fact a step's date comes from. `programme: visa` (Slice 9 Task 11, F1): a step that is not fanned out takes
    the fact of the programme the student's visa file is for (before they choose: the earliest of the plan's
    candidate programmes). `note`: the plain explanation shown with the date, e.g. "Apply by {due}: {weeks} weeks
    before your semester starts on {date}" ({date} is the fact's date, {due} the step's own due date, {days} and
    {weeks} the lead time; any playbook constant by its name, e.g. {visa_processing_days}); `note_earliest`: the same
    when the date is the earliest of several programmes'. `waiting`: what the student is told while the fact is
    missing; `waiting_none`: while no programme is left to take it from (every one said "not admitted")."""
    fact: str
    programme: Literal["visa"] | None = None
    note: str | None = None
    note_earliest: str | None = None  # the note when the date is the earliest of several programmes' (provisional)
    waiting: str | None = None
    waiting_none: str | None = None  # blocked `no_candidate:<programme>` (Slice 9 Task 11)

    @field_validator("note", "note_earliest")
    @classmethod
    def _plain_placeholders(cls, note: str | None) -> str | None:
        """Only plain names ({due}, not {due.year} or {0}); which names are known is checked by the playbook."""
        if note is not None:
            for name in placeholders(note):
                if not name.isidentifier():
                    raise ValueError(f"note placeholder {{{name}}} must be a plain name")
        return note


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
        if self.anchor and self.anchor.programme and self.fan_out == "programme":
            raise ValueError(f"a fanned-out step anchors on its own programme, not anchor.programme "
                             f"({self.template_key})")
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
    eligibility: EligibilityRules | None = None  # Slice 4: the route's eligibility checks (S4-D2)
    self_serve: SelfServe | None = None  # Slice 4: what the route builder completes (S4-D9)

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
            for note in (t.anchor.note, t.anchor.note_earliest) if t.anchor else ():
                unknown = placeholders(note or "") - NOTE_FIELDS - set(self.constants)
                if unknown:
                    raise ValueError(f"unknown note placeholder {sorted(unknown)} in {t.template_key} (known: "
                                     f"{sorted(NOTE_FIELDS)} and the playbook's constants)")
            if self.require_citations and not t.citations and not t.citation_from_fact:
                raise ValueError(f"task {t.template_key} needs a citation (require_citations is on)")
        return self

    def task(self, template_key: str) -> TaskTemplate:
        return next(t for t in self.tasks if t.template_key == template_key)
