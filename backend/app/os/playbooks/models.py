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
    """`pull: false` (Slice 9b): the step still waits for the dependency (a hard edge gates it), but the step's own
    date does not pull the dependency earlier in the backward pass. For a step whose date is a target the student
    cannot bring forward through it, e.g. the visa apply-by date and the admission result (Task 11C)."""
    key: str
    hard: bool = True
    pull: bool = True


class Condition(_Model):
    fact: str
    in_: list[str] | None = Field(None, alias="in")
    present: bool | None = None

    @model_validator(mode="after")
    def _one_test(self) -> "Condition":
        if (self.in_ is None) == (self.present is None):
            raise ValueError("condition needs exactly one of 'in' or 'present'")
        return self


NOTE_FIELDS = frozenset({"date", "due", "days", "weeks", "days_left"})


def placeholders(note: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(note) if name is not None}


class Anchor(_Model):
    """The fact a step's date comes from. `programme: visa` (Slice 9 Task 11, F1): a step that is not fanned out takes
    the fact of the programme the student's visa file is for (before they choose: the earliest of the plan's
    candidate programmes). `note`: the plain explanation shown with the date, e.g. "Apply by {due}: {weeks} weeks
    before your semester starts on {date}" ({date} is the fact's date, {due} the step's own due date, {days} and
    {weeks} the lead time; any playbook constant by its name, e.g. {visa_processing_days}); `note_earliest`: the same
    when the date is the earliest of several programmes'. `waiting`: what the student is told while the fact is
    missing; `waiting_none`: while no programme is left to take it from (every one said "not admitted").
    `note_passed` (Slice 9b): when set, a date the lead time gives that has already passed when the plan is compiled
    is never shown as the due date; the step is due on the fact's own date instead (the last day the step still
    makes sense) and shows this note ({due} is then the passed date, {days_left} the days from today to the fact's
    date); `note_passed_earliest`: the same when the date is the earliest of several programmes'."""
    fact: str
    programme: Literal["visa"] | None = None
    note: str | None = None
    note_earliest: str | None = None  # the note when the date is the earliest of several programmes' (provisional)
    waiting: str | None = None
    waiting_none: str | None = None  # blocked `no_candidate:<programme>` (Slice 9 Task 11)
    note_passed: str | None = None  # the lead time's date has passed: due on the fact's date (Slice 9b)
    note_passed_earliest: str | None = None

    def notes(self) -> tuple[str | None, ...]:
        return self.note, self.note_earliest, self.note_passed, self.note_passed_earliest

    @field_validator("note", "note_earliest", "note_passed", "note_passed_earliest")
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
        if self.anchor and (self.anchor.note_passed or self.anchor.note_passed_earliest) and not self.lead_time:
            raise ValueError(f"anchor.note_passed needs a lead_time: without one the date cannot pass early "
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
            for note in t.anchor.notes() if t.anchor else ():
                unknown = placeholders(note or "") - NOTE_FIELDS - set(self.constants)
                if unknown:
                    raise ValueError(f"unknown note placeholder {sorted(unknown)} in {t.template_key} (known: "
                                     f"{sorted(NOTE_FIELDS)} and the playbook's constants)")
                if "weeks" in placeholders(note or ""):  # {weeks} is the lead time / 7: anything else shows wrong
                    lead = 0 if not t.lead_time else t.lead_time.days if t.lead_time.days is not None \
                        else self.constants[t.lead_time.constant].value
                    if not str(lead).isdigit() or int(lead) % 7:
                        raise ValueError(f"note of {t.template_key} says {{weeks}}: its lead time ({lead} days) must "
                                         f"be in whole weeks (a multiple of 7), or the note must say {{days}}")
            if self.require_citations and not t.citations and not t.citation_from_fact:
                raise ValueError(f"task {t.template_key} needs a citation (require_citations is on)")
        return self

    def task(self, template_key: str) -> TaskTemplate:
        return next(t for t in self.tasks if t.template_key == template_key)
