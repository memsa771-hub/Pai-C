"""Official calendars as registry rows with cycle-bound date facts (P2 spec §4.11; master R-20, R-26, R-33).

A calendar is a registry row of kind `calendar` with `attrs.calendar_type` (the types and their date fields are data in
`calendars.yaml`). Its dates are Knowledge facts of scope `registry`, ref = the calendar id, one per intake, valued
`{"date": "YYYY-MM-DD", "tz": "Area/City"}`: the shape the plan compiler already reads. Nothing here names a board, a
country or a date."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from app.os.knowledge.fact_classes import classes
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from app.os.registry.model import RegistryEntry
from app.os.registry.store import Recorded, RegistryStore

CALENDARS_FILE = Path(__file__).with_name("calendars.yaml")
FactChanged = Callable[[str, str, str, int, str, int], object]


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class CalendarType:
    key: str
    label: str
    fields: dict[str, str]  # date field -> fact class


@cache
def _load(path: Path = CALENDARS_FILE) -> dict[str, CalendarType]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    known = classes()
    out = {}
    for key, block in data["types"].items():
        fields = dict(block["fields"])
        bad = sorted(c for c in fields.values() if c not in known)
        if bad:
            raise ValueError(f"calendar type {key}: unknown fact classes {bad}")
        out[key] = CalendarType(key, block["label"], fields)
    return out


def calendar_types() -> dict[str, CalendarType]:
    return dict(_load())


def record_calendar(registry: RegistryStore, entry: RegistryEntry, calendar_type: str, *, cause: str,
                    cause_ref: str | None = None, actor: str | None = None) -> Recorded:
    """Records a `calendar` row with its type. A calendar keeps its type once recorded."""
    if entry.kind != "calendar":
        raise CalendarError(f"{entry.entity_id} is a {entry.kind}, not a calendar")
    if calendar_type not in _load():
        raise CalendarError(f"unknown calendar type '{calendar_type}' (use one of {sorted(_load())})")
    old = registry.get(entry.entity_id)
    if old is not None and old.attrs.get("calendar_type") not in (None, calendar_type):
        raise CalendarError(f"{entry.entity_id} is a {old.attrs['calendar_type']} calendar; its type cannot change")
    return registry.record(replace(entry, attrs={**entry.attrs, "calendar_type": calendar_type}), cause=cause,
                           cause_ref=cause_ref, actor=actor)


def record_calendar_date(registry: RegistryStore, knowledge: SqlKnowledge, calendar_id: str, field: str, day: date, *,
                         tz: str, url: str, quote: str, checked_at: datetime, intake_year: int, intake_term: str,
                         status: str = "confirmed", cause: str, cause_ref: str | None = None,
                         actor: str | None = None, source: str = "manual", read_method: str | None = None,
                         language: str | None = None, evidence: list | None = None,
                         on_change: FactChanged | None = None) -> int:
    """One date of a calendar for one intake, as a fact. The field must belong to the calendar's type; the fact class
    comes from the vocabulary. `tz` is required: a date without its zone could be a day off for a student elsewhere (the
    caller takes it from the calendar or, failing that, from its parent). `verified` is reached only through review (T1),
    never here. `on_change(scope, ref, field, fact_id, status, intake_year)` is called after the write, so the plans
    that use the date follow it (row 6.10): pass the plan service's `after_fact_change`."""
    cal = registry.get(calendar_id)
    if cal is None:
        raise CalendarError(f"{calendar_id} is not in the registry")
    if cal.kind != "calendar":
        raise CalendarError(f"{calendar_id} is not a calendar ({cal.kind})")
    ctype = _load().get(cal.attrs.get("calendar_type", ""))
    if ctype is None:
        raise CalendarError(f"{calendar_id} has no calendar type; record it with record_calendar")
    if field not in ctype.fields:
        raise CalendarError(f"field '{field}' is not a date of a {ctype.key} calendar ({sorted(ctype.fields)})")
    if not tz:
        raise CalendarError("a calendar date needs its timezone")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise CalendarError(f"unknown timezone '{tz}'") from None
    fact = Fact(value={"date": day.isoformat(), "tz": tz}, quote=quote, url=url, checked_at=checked_at,
                intake_year=intake_year, status=status, intake_term=intake_term, fact_class=ctype.fields[field],
                read_method=read_method, language=language)  # validates the trust rules
    fid = knowledge.upsert("registry", calendar_id, field, fact, source=source, evidence=evidence, cause=cause,
                           cause_ref=cause_ref, actor=actor)
    if on_change is not None:
        on_change("registry", calendar_id, field, fid, status, intake_year)
    return fid


def calendar_dates(knowledge: SqlKnowledge, calendar_ids: Sequence[str], intake_year: int,
                   **read) -> dict[tuple[str, str], Fact]:
    """The date facts of the calendars for an intake: {(calendar id, field): fact}. `read` takes the knowledge read
    options (`intake_term`, `fallback_previous`, `fallback_year`)."""
    fields = sorted({f for t in _load().values() for f in t.fields})
    return knowledge.registry_facts(list(calendar_ids), fields, intake_year, **read)
