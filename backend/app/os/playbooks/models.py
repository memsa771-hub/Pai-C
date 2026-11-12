"""Playbook schema: a versioned route template, validated at load time (spec §4.1)."""

import re
from datetime import date
from string import Formatter
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.os.contracts.student_facts import FACT_KEY
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


REQUEST_TEMPLATES = ("provide", "which_is_right", "result_expected")  # template keys of the compiler's request steps
Evidence = Literal["stated", "shown", "confirmed"]


class Need(_Model):
    """What a step needs before it can run (R-17, R-18): a student fact (a StudentFacts key) or a document (a document
    type), held at least at `evidence`. A document is never merely `stated`, and no reviewer confirms one in P1, so a
    document need is `shown` (checked by the playbook)."""
    fact: str | None = Field(None, pattern=FACT_KEY)
    document: str | None = Field(None, pattern=r"^[a-z_][a-z0-9_]*$")
    evidence: Evidence

    @model_validator(mode="after")
    def _one_ref(self) -> "Need":
        if (self.fact is None) == (self.document is None):
            raise ValueError("a need names exactly one of 'fact' or 'document'")
        return self

    @property
    def ref(self) -> str:
        return self.fact or self.document or ""

    @property
    def kind(self) -> Literal["fact", "document"]:
        return "fact" if self.fact is not None else "document"


class Expected(_Model):
    """`fact`: a route Knowledge fact holding the date the result comes out (the calendar); `title`: the step shown
    until then (R-20)."""
    fact: str
    title: str = Field(min_length=1)


class Ask(_Model):
    """The route's words for one request, keyed in `Playbook.asks` by the fact key or the document type: the title of
    the provide step per evidence level (`stated`, `shown`, `confirmed`), of the which-is-right step, and the
    provide step's own duration. `expected`: the result-expected step, on a fact only. `citations`: where the route
    says this is required; with `require_citations` every ask a need uses has one (never an invented requirement)."""
    stated: str | None = None
    shown: str | None = None
    confirmed: str | None = None
    which_is_right: str | None = None
    duration_days: int = Field(1, ge=0)
    expected: Expected | None = None
    citations: list[Citation] = []


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
    needs: list[Need] = []  # P1-T8: the facts and documents this step needs, each at an evidence level (R-18)

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


PAGE_KEYS = ("start", "inbox", "documents", "programmes", "statements", "pack", "visa")  # the OS's own pages


class Page(_Model):
    """One page of the student's plan on this route: the OS page `key` (route `os-<key>`), its menu `label`, its
    heading `title` and, on `pack`/`visa`, the `noun` the page uses for what it builds (R-52)."""
    key: Literal["start", "inbox", "documents", "programmes", "statements", "pack", "visa"]
    label: str = Field(min_length=1)
    title: str = Field(min_length=1)
    noun: str | None = None


class SourceCheck(_Model):
    """The day a playbook source (`S<n>`) was last read against its page (R-54), and whether the reviewer of that
    reading confirmed it. An unconfirmed source is shown as "not confirmed", never as checked and settled."""
    checked: date
    confirmed: bool = True


_SOURCE_ID = re.compile(r"S\d+")


class AppliesTo(_Model):
    """P2-D25 / R-65: the intakes a playbook version is for. `term` (any term when left out) and `from_year`: the first
    intake year it applies to. A version with no `applies_to` applies to every intake. Pinned plans do not move."""
    term: str | None = None
    from_year: int = Field(ge=2000)

    @field_validator("term")
    @classmethod
    def _plain_term(cls, term: str | None) -> str | None:
        if term is not None and not re.fullmatch(r"[a-z_]+", term):
            raise ValueError(f"intake term '{term}' must be lowercase letters and underscores")
        return term

    def covers(self, term: str, year: int) -> bool:
        return (self.term is None or self.term == term) and year >= self.from_year


class Playbook(_Model):
    key: str
    version: int = Field(ge=1)
    route: Route
    default_timezone: str
    require_citations: bool = False
    applies_to: AppliesTo | None = None  # P2-D25: the intakes this version is for; None = all
    intake_terms: list[str] = []  # the intake terms the route offers (D-g), e.g. one lowercase word per term
    constants: dict[str, Constant] = {}
    tasks: list[TaskTemplate]
    eligibility: EligibilityRules | None = None  # Slice 4: the route's eligibility checks (S4-D2)
    self_serve: SelfServe | None = None  # Slice 4: what the route builder completes (S4-D9)
    asks: dict[str, Ask] = {}  # P1-T8: the route's words for each request, by fact key or document type
    # Display data (P1-T9). Never in the playbook file itself: the loader joins it from `pages/<key>.v<n>.yaml`
    # so a file a running plan pins stays as it was (invariant 10). Compile ignores both.
    pages: list[Page] | None = None  # None: not declared
    sources: dict[str, SourceCheck] = {}

    @property
    def declares_needs(self) -> bool:
        """A v2 playbook: some step needs a student fact or document. Chosen only while the student's needs gate is on."""
        return any(t.needs for t in self.tasks)

    @field_validator("intake_terms")
    @classmethod
    def _plain_terms(cls, terms: list[str]) -> list[str]:
        for term in terms:
            if not re.fullmatch(r"[a-z_]+", term):  # the same shape as IntakeRef.term
                raise ValueError(f"intake term '{term}' must be lowercase letters and underscores")
        return terms

    @field_validator("default_timezone")
    @classmethod
    def _known_timezone(cls, tz: str) -> str:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone '{tz}'") from None
        return tz

    @model_validator(mode="after")
    def _applies_to_a_declared_term(self) -> "Playbook":
        if self.applies_to and self.applies_to.term and self.intake_terms \
                and self.applies_to.term not in self.intake_terms:
            raise ValueError(f"applies_to term '{self.applies_to.term}' is not one of intake_terms")
        return self

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
        self._check_needs()
        self._check_pages()
        self._check_sources()
        return self

    def _check_needs(self) -> None:
        reserved = sorted(t.template_key for t in self.tasks if t.template_key in REQUEST_TEMPLATES)
        if reserved:
            raise ValueError(f"template_key {reserved} is reserved for the steps PAI adds for a missing fact")
        documents = {n.document for t in self.tasks for n in t.needs if n.document}
        used = {n.ref for t in self.tasks for n in t.needs}
        unused = sorted(set(self.asks) - used)
        if unused:
            raise ValueError(f"'asks' entry {unused} is not needed by any step")
        for t in self.tasks:
            refs = [n.ref for n in t.needs]
            twice = sorted({r for r in refs if refs.count(r) > 1})
            if twice:
                raise ValueError(f"{t.template_key} lists the need {twice} more than once")
            for need in t.needs:
                ask = self.asks.get(need.ref)
                if ask is None:
                    raise ValueError(f"{t.template_key} needs {need.ref} but it has no entry in 'asks'")
                if need.kind == "document" and need.evidence != "shown":
                    raise ValueError(f"a document need must be 'shown' ({t.template_key}: {need.ref}): a paper is "
                                     f"never merely stated, and no reviewer confirms a document")
                if getattr(ask, need.evidence) is None:
                    raise ValueError(f"{t.template_key} needs {need.ref} '{need.evidence}' but its 'asks' entry has "
                                     f"no '{need.evidence}' title")
                if self.require_citations and not ask.citations:
                    raise ValueError(f"the 'asks' entry of {need.ref} needs a citation (require_citations is on)")
                if need.kind == "fact" and not ask.which_is_right:
                    raise ValueError(f"the 'asks' entry of {need.ref} needs a which_is_right title (two sources may "
                                     f"disagree)")
        for ref, ask in self.asks.items():
            if ask.expected is not None and ref in documents:
                raise ValueError(f"'asks' entry {ref}: 'expected' (a result still to come) belongs on a fact, not a "
                                 f"document")

    def _check_pages(self) -> None:
        keys = [p.key for p in self.pages or []]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"duplicate page key {dupes}")
        if "visa" in keys and self.route.destination == self.route.origin:
            raise ValueError("a visa page needs a route that leaves the country (destination differs from origin)")
        for p in self.pages or []:
            if p.noun is not None and p.key not in ("pack", "visa"):
                raise ValueError(f"page '{p.key}' cannot have a noun (only pack and visa)")

    def _check_sources(self) -> None:
        if not self.sources:
            return
        cited = {c.source for t in self.tasks for c in t.citations} | \
                {c.source for k in self.constants.values() for c in k.citations} | \
                {c.source for a in self.asks.values() for c in a.citations}
        missing = sorted(s for s in cited if _SOURCE_ID.fullmatch(s) and s not in self.sources)
        if missing:
            raise ValueError(f"source {missing} is cited but has no checked date in 'sources'")

    def task(self, template_key: str) -> TaskTemplate:
        return next(t for t in self.tasks if t.template_key == template_key)
