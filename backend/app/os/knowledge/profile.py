"""Research profile: per-route field definitions as data (Slice 2 spec §4.2, invariant 12).

Python knows only generic field types. Enum values, aliases, official domains, month names and phrases
live in the route's YAML profile, and the reading model the research agent fills is built from it.
"""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, create_model, model_validator

PROFILE_DIR = Path(__file__).parent / "profiles"

# numbers: like grade, named numeric parts each stated in the quote (Slice 5: a statement's length limit)
FieldType = Literal["enum", "amount", "month_day", "level", "level_scores", "grade", "numbers", "name_set",
                    "season_set"]
MonthDay = Annotated[str, StringConstraints(pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")]
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


class ProfileError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldSpec(_Model):
    name: str
    type: FieldType
    hint: str
    cycle_bound: bool = False
    # one value for every programme of a university (the semester's lecture start): the university's own academic
    # calendar page counts as in scope for it, though it names no programme (trust.scope_ok)
    university_wide: bool = False
    # month_day: the date falls in the intake's own year (a winter lecture start), so the year the quote writes with
    # the date is the fact's cycle, not the end of a period after it (trust.cycle_year)
    value_year_is_cycle: bool = False
    # value -> aliases a quote may use (enum, name_set, season_set); level_scores: score or flag -> aliases
    values: dict[str, list[str]] = {}
    levels: list[str] = []  # level, level_scores
    scores: list[str] = []  # level_scores: the numeric test scores
    flags: list[str] = []  # level_scores, numbers: yes/no facts, e.g. whether a letter is accepted instead of a test
    parts: list[str] = []  # grade, numbers: the numeric parts

    @model_validator(mode="after")
    def _type_needs(self) -> "FieldSpec":
        if self.type in ("enum", "name_set", "season_set") and not self.values:
            raise ValueError(f"field '{self.name}' ({self.type}) needs values")
        if self.type in ("level", "level_scores") and not self.levels:
            raise ValueError(f"field '{self.name}' ({self.type}) needs levels")
        if self.type == "level_scores" and not self.scores:
            raise ValueError(f"field '{self.name}' (level_scores) needs scores")
        if self.type == "level_scores":
            for key in self.values:
                if key not in (*self.scores, *self.flags):
                    raise ValueError(f"field '{self.name}': values names unknown score or flag '{key}'")
        if self.value_year_is_cycle and self.type != "month_day":
            raise ValueError(f"field '{self.name}': value_year_is_cycle is for month_day fields")
        if self.type in ("grade", "numbers") and not self.parts:
            raise ValueError(f"field '{self.name}' ({self.type}) needs parts")
        if self.type == "numbers":
            for key in self.values:
                if key not in self.flags:
                    raise ValueError(f"field '{self.name}': values names unknown flag '{key}'")
        return self


class ResearchProfile(_Model):
    key: str
    version: int = Field(ge=1)
    route_key: str
    official_sources: list[str]
    link_keywords: list[str]
    month_names: dict[int, list[str]]
    none_phrases: dict[str, list[str]] = {}
    exclusive_phrases: list[str]
    scope_all_phrases: list[str] = []  # a scope quote with one of these says a rule is for every programme
    # a page whose title names one of these is the university's academic calendar (for university_wide fields)
    university_wide_titles: list[str] = []
    # Told to every reader with the run's intake year (readings.user_prompt), so a page that lists several
    # semesters gives the intake's. Placeholders: {year}, {next_year}, {next_yy}. Empty: nothing is said.
    target_cycle: str = ""
    draft_email: str
    fields: list[FieldSpec]

    @model_validator(mode="after")
    def _consistent(self) -> "ResearchProfile":
        names = [f.name for f in self.fields]
        for name in names:
            if names.count(name) > 1:
                raise ValueError(f"duplicate field '{name}'")
        for name in self.none_phrases:
            if name not in names:
                raise ValueError(f"none_phrases names unknown field '{name}'")
        for f in self.fields:
            if f.university_wide and not self.university_wide_titles:
                raise ValueError(f"university_wide field '{f.name}' needs university_wide_titles")
        try:
            self.target_cycle_for(2027)
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(f"target_cycle has an unknown placeholder: {e}") from None
        if set(self.month_names) != set(range(1, 13)):
            raise ValueError("month_names needs all 12 months")
        for domain in self.official_sources:
            if not _DOMAIN.match(domain):
                raise ValueError(f"official source '{domain}' must be a bare domain like example.org")
        return self

    def target_cycle_for(self, intake_year: int) -> str:
        """The profile's target-cycle wording for one intake year, e.g. 2027 -> '... WS 2027/28 ...'."""
        return self.target_cycle.format(year=intake_year, next_year=intake_year + 1,
                                        next_yy=f"{(intake_year + 1) % 100:02d}")

    def field(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)


def load_profile(path: Path) -> ResearchProfile:
    try:
        return ResearchProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as e:
        raise ProfileError(f"{path.name}: invalid YAML: {e}") from e
    except ValidationError as e:
        raise ProfileError(f"{path.name}: {e}") from e


def load_profile_dir(directory: Path = PROFILE_DIR) -> dict[str, ResearchProfile]:
    """The newest profile per route key."""
    seen: dict[tuple[str, int], str] = {}
    newest: dict[str, ResearchProfile] = {}
    for path in sorted(directory.glob("*.research.v*.yaml")):
        profile = load_profile(path)
        ident = (profile.route_key, profile.version)
        if ident in seen:
            raise ProfileError(f"{path.name}: duplicate profile {profile.route_key} v{profile.version} "
                               f"(also in {seen[ident]})")
        seen[ident] = path.name
        if profile.route_key not in newest or profile.version > newest[profile.route_key].version:
            newest[profile.route_key] = profile
    return newest


_FORBID = ConfigDict(extra="forbid")


def _literal(values) -> Any:
    return Literal[tuple(values)]


def _value_type(spec: FieldSpec) -> Any:
    """The Python type of a field's value, built from its generic type and the profile's values."""
    if spec.type == "enum":
        return _literal(spec.values)
    if spec.type == "amount":
        return float
    if spec.type == "month_day":
        return MonthDay
    if spec.type == "season_set":
        return list[_literal(spec.values)]
    model = f"{spec.name}_value"
    if spec.type == "level":
        return create_model(model, __config__=_FORBID,
                            level=(_literal(["none", *spec.levels]), Field(description="'none' if not required")),
                            when=(str | None, Field(None, description="When it must be shown")))
    if spec.type == "level_scores":
        parts: dict[str, Any] = {"cefr": (_literal(spec.levels) | None, None)}
        parts |= {s: (float | None, None) for s in spec.scores}
        parts |= {f: (bool | None, None) for f in spec.flags}
        return create_model(model, __config__=_FORBID, **parts)
    if spec.type in ("grade", "numbers"):
        parts = {p: (float | None, None) for p in spec.parts} | {f: (bool | None, None) for f in spec.flags}
        return create_model(model, __config__=_FORBID, **parts)
    # name_set: the tests (or other named items) that satisfy the requirement; empty if none is required
    return create_model(model, __config__=_FORBID,
                        any_of=(list[_literal(spec.values)], Field(description="Empty if none is required")))


def _found_model(spec: FieldSpec) -> type[BaseModel]:
    return create_model(
        f"{spec.name}_found", __config__=_FORBID,
        value=(_value_type(spec), ...),
        quote=(str, Field(description="The sentence or table entry that states the fact, copied word for word")),
        url=(str, Field(description="The URL of the page the quote is on, exactly as given in its PAGE header")),
        cycle=(str | None, Field(None, description="The intake or year the page gives for this fact, copied; "
                                                    "null if none")),
        scope_quote=(str | None, Field(None, description="On a page about several programmes: the sentence that "
                                                          "says which programmes this rule is for, copied")),
    )


def reading_model(profile: ResearchProfile) -> type[BaseModel]:
    """One reading of a programme's pages: every field optional (None = the pages do not state it)."""
    fields = {f.name: (_found_model(f) | None, Field(None, description=f.hint)) for f in profile.fields}
    return create_model(f"Reading_{profile.route_key}_v{profile.version}", __config__=_FORBID, **fields)
