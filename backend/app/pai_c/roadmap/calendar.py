"""The dated academic calendar (policy/academic_calendar.json) the time
estimate reads (spec FOUR_FEATURES_SPEC.md §4.2).

Dates are world facts, so each one keeps where it came from and how sure the
research was; a month nobody found stays empty and the estimate says "date not
confirmed" instead of guessing. The loader refuses a file that breaks those
rules, so a bad edit fails at load (and in the data test), never as a wrong
date on a student's card.
"""

from functools import lru_cache

from app.pai_c.paths.fields import study_fields
from app.pai_c.policy.controller import load_data

CONFIDENCE = ("official", "secondary", "uncertain")
_DEGREE_META = {"_note", "sources", "confidence"}


class CalendarError(ValueError):
    pass


def _months(where: str, values) -> None:
    for month in values or ():
        if not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
            raise CalendarError(f"{where}: month {month!r} is not 1-12")


def _sourced(where: str, row: dict) -> None:
    sources = row.get("sources") or []
    if not any(isinstance(url, str) and url.startswith("https://") for url in sources):
        raise CalendarError(f"{where}: needs at least one https source")
    if row.get("confidence") not in CONFIDENCE:
        raise CalendarError(f"{where}: confidence must be one of {CONFIDENCE}")


def validate(data: dict) -> dict:
    """The calendar's rules: every event, intake and test is sourced and has a
    confidence, months are 1-12, and degree_years names study fields."""
    if not data.get("as_of"):
        raise CalendarError("as_of is required")
    for event in data["events"]:
        where = f"event {event.get('key')}"
        _sourced(where, event)
        _months(where, event.get("months"))
    for intake in data["intakes"]:
        where = f"intake {intake.get('key')}"
        _sourced(where, intake)
        _months(where, intake.get("apply_months"))
        _months(where, intake.get("merit_list_months"))
        if intake.get("classes_start_month") is not None:
            _months(where, [intake["classes_start_month"]])
    for test in data["tests"]:
        where = f"test {test.get('key')}"
        _sourced(where, test)
        for name in ("register_months", "test_months", "result_months"):
            _months(where, test.get(name))
    keys = [row["key"] for row in data["events"] + data["tests"] + data["intakes"]]
    if len(keys) != len(set(keys)):
        raise CalendarError("event, test and intake keys must be unique")
    fields = study_fields()
    for key, years in data["degree_years"].items():
        if key in _DEGREE_META:
            continue
        if key not in fields:
            raise CalendarError(f"degree_years: {key} is not a study field")
        if not isinstance(years, int) or years <= 0:
            raise CalendarError(f"degree_years: {key} needs a whole number of years")
    return data


@lru_cache(maxsize=1)
def calendar() -> dict:
    return validate(load_data("academic_calendar.json"))


def event(key: str) -> dict | None:
    """An event or a test as one shape {key, months, sources, confidence}: a
    test's months are its test months, and `<test>:result` names its result
    months, so a step can wait for a test result like a board result."""
    data = calendar()
    if key.endswith(":result"):
        test = event(key.removesuffix(":result"))
        return {**test, "key": key, "months": test["result_months"]} if test and "result_months" in test else None
    for row in data["events"]:
        if row["key"] == key:
            return {"key": key, "months": list(row.get("months") or []), "sources": row["sources"],
                    "confidence": row["confidence"]}
    for row in data["tests"]:
        if row["key"] == key:
            return {"key": key, "months": list(row.get("test_months") or []), "sources": row["sources"],
                    "confidence": row["confidence"], "result_months": list(row.get("result_months") or [])}
    return None


def calendar_test(codes) -> dict | None:
    """The calendar test of the first catalog code that has one."""
    for code in codes:
        for row in calendar()["tests"]:
            if code in row.get("codes", ()):
                return row
    return None


def intakes_for(field_key: str) -> list[dict]:
    study = study_fields().get(field_key)
    family = study.family if study else None
    return [row for row in calendar()["intakes"]
            if field_key in row.get("fields", ()) or (family and family in row.get("families", ()))]


def degree_years(field_key: str) -> int | None:
    years = calendar()["degree_years"].get(field_key)
    return years if field_key not in _DEGREE_META and isinstance(years, int) else None
