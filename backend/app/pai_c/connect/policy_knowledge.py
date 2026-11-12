"""Freeze exception 3 (P2-D28, master §10, R-44): the Counsellor's academic calendar and admission rules read through
Knowledge, in today's shape.

With `CONNECT_CALENDAR_FROM_KNOWLEDGE` on (and the OS `counsellor` module on), a value that a link in
`policy_links.yaml` names is replaced by its confirmed Knowledge fact, and the fact's URL leads the row's sources.
Every other value is the policy file's own, so the shape and the unlinked values stay as today; the time estimate
changes only where the import verified a value (P2 spec §4.11). An unconfirmed fact, a missing fact, an OS failure
or a value of the wrong kind leaves the file's value: nothing is guessed. With the part off the files are returned
untouched (the same object), so the Counsellor behaves as before.

Links name Knowledge facts by `(scope, ref, field)`; they are data, added when a row is imported, never guessed.
"""

import copy
import logging
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import config

log = logging.getLogger(__name__)

PART = "CONNECT_CALENDAR_FROM_KNOWLEDGE"
_LINKS = Path(__file__).with_name("policy_links.yaml")
_TTL_SECONDS = 300  # a fact confirmed or moved is read within five minutes
_SECTIONS = {"event": "events", "test": "tests", "intake": "intakes"}
_MONTH_ATTRS = {
    "events": ("months",),
    "tests": ("register_months", "test_months", "result_months"),
    "intakes": ("apply_months", "merit_list_months", "classes_start_month"),
}
_RULE_ATTRS = ("min_percent", "years")
_cache: dict[str, tuple[float, int, dict]] = {}


@lru_cache(maxsize=1)
def links() -> dict:
    data = yaml.safe_load(_LINKS.read_text(encoding="utf-8")) or {}
    return {"calendar": list(data.get("calendar") or []), "admission_rules": list(data.get("admission_rules") or [])}


def _key(link: dict) -> tuple[str, str, str]:
    fact = link["fact"]
    return (fact["scope"], fact["ref"], fact["field"])


def _month(value) -> int | None:
    """The month of a date fact (`{"date": "YYYY-MM-DD", ...}`); None for any other value."""
    text = value.get("date") if isinstance(value, dict) else None
    try:
        return date.fromisoformat(text).month if isinstance(text, str) else None
    except ValueError:
        return None


def _number(value) -> float | int | None:
    """A plain number, or the `value` of `{"value", "unit"}` when it is one; None otherwise (text is never read)."""
    raw = value.get("value") if isinstance(value, dict) else value
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw


def _lead(sources: list, url: str) -> list:
    return [url, *[s for s in sources if s != url]]


def overlay_calendar(data: dict, facts: dict) -> dict:
    """The calendar with each linked month replaced by its confirmed fact's month. A row whose every month attribute
    came from a confirmed fact is `official`; a partly linked row keeps its own confidence."""
    out = copy.deepcopy(data)
    done: dict[int, set] = {}
    for link in links()["calendar"]:
        section, attr = _SECTIONS.get(link.get("target")), link.get("attr")
        fact = facts.get(_key(link))
        if section is None or attr not in _MONTH_ATTRS[section] or fact is None:
            continue
        row = next((r for r in out[section] if r.get("key") == link.get("key")), None)
        month = _month(fact["value"])
        if row is None or month is None:
            continue
        row[attr] = month if attr == "classes_start_month" else [month]
        row["sources"] = _lead(row.get("sources") or [], fact["url"])
        done.setdefault(id(row), set()).add(attr)
        if all(a in done[id(row)] for a in _MONTH_ATTRS[section] if a in row):
            row["confidence"] = "official"
    return out


def overlay_rules(data: dict, facts: dict) -> dict:
    """The admission rules with each linked `min_percent` or `years` replaced by its confirmed fact; the rule keeps
    its own confidence (other values in it are still the file's)."""
    out = copy.deepcopy(data)
    for link in links()["admission_rules"]:
        attr, fact = link.get("attr"), facts.get(_key(link))
        if attr not in _RULE_ATTRS or fact is None:
            continue
        row = next((r for r in out["rules"] if r.get("applies_to") == link.get("applies_to")), None)
        number = _number(fact["value"])
        if row is None or number is None or (attr == "years" and not float(number).is_integer()):
            continue
        row[attr] = int(number) if attr == "years" else number
        row["sources"] = _lead(row.get("sources") or [], fact["url"])
    return out


def _on() -> bool:
    from app.pai_c.connect.flags import part_on

    return part_on(PART)


def _read(name: str, data: dict, overlay, finish, today: date | None) -> dict:
    if not getattr(config, PART):
        return data
    now = time.monotonic()
    hit = _cache.get(name)
    if hit is not None and hit[1] == id(data) and now - hit[0] < _TTL_SECONDS:
        return hit[2]
    result = data
    entries = links()[name]
    if entries and _on():
        from app import pai_os_bridge

        facts = pai_os_bridge.confirmed_knowledge([_key(e) for e in entries], (today or date.today()).year)
        if facts:
            try:
                result = finish(overlay(data, facts))
            except ValueError:  # an overlaid row breaks the file's rules (e.g. a source that is not https)
                log.exception("the %s from Knowledge failed its checks; the policy file is used", name)
    _cache[name] = (now, id(data), result)
    return result


def calendar(data: dict, validate, today: date | None = None) -> dict:
    """The academic calendar the Counsellor reads; `validate` keeps the file's rules on the overlaid result."""
    return _read("calendar", data, overlay_calendar, validate, today)


def admission_rules(data: dict, today: date | None = None) -> dict:
    return _read("admission_rules", data, overlay_rules, lambda d: d, today)


def clear() -> None:
    _cache.clear()
    getattr(links, "cache_clear", lambda: None)()  # a test may have replaced `links`
