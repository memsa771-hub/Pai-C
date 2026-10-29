"""The dated academic calendar (policy/academic_calendar.json) the time
estimate reads (spec FOUR_FEATURES_SPEC.md §4.2).

Dates are world facts, so each one keeps where it came from and how sure the
research was; a month nobody found stays empty and the estimate says "date not
confirmed" instead of guessing. The loader refuses a file that breaks those
rules, so a bad edit fails at load (and in the data test), never as a wrong
date on a student's card.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.pai_c.memory import vault_catalog
from app.pai_c.paths.fields import study_fields
from app.pai_c.policy.controller import load_data

CONFIDENCE = ("official", "secondary", "uncertain")
_DEGREE_META = {"_note", "sources", "confidence"}
# Region names live in the data: the region marked `fallback` is used when
# nothing else places the student; a region's `levels` (catalog education
# levels, e.g. O/A level) send those students there whatever their board.
_REGION_META = {"fallback", "levels", "boards", "overrides", "gaps", "_note", "national_fallback_confidence", "ibcc_lag_months",
                "ibcc_sources", "ibcc_confidence"}
_BOARDS_CATALOG = Path(__file__).resolve().parents[2] / "memory" / "catalog" / "vault_catalog.json"


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


def region_events(region: dict) -> dict:
    """A region's dated rows by event key (everything that is not region metadata)."""
    return {key: row for key, row in region.items() if key not in _REGION_META and isinstance(row, dict)}


def _validate_regions(data: dict) -> None:
    """Region rows follow the same rules as national ones (a region may carry
    an event no national row has, such as a supplementary result), and the
    cities map only to known regions."""
    regions = data.get("regions", {})
    for name, region in regions.items():
        for key, row in region_events(region).items():
            where = f"region {name} event {key}"
            _sourced(where, row)
            _months(where, row.get("months"))
        if fallback_confidence(region) not in CONFIDENCE:
            raise CalendarError(f"region {name}: national_fallback_confidence must be one of {CONFIDENCE}")
        if region.get("ibcc_lag_months") is not None:
            _sourced(f"region {name} ibcc", {"sources": region.get("ibcc_sources"),
                                              "confidence": region.get("ibcc_confidence")})
    fallbacks = [name for name, region in regions.items() if region.get("fallback") is True]
    if len(fallbacks) != 1:
        raise CalendarError(f"exactly one region must be marked fallback, found {fallbacks}")
    for intake in data["intakes"]:
        for name in intake.get("regions", ()):
            if name not in regions:
                raise CalendarError(f"intake {intake['key']}: unknown region {name}")
    for city, name in data.get("city_regions", {}).items():
        if city != "_note" and name not in regions:
            raise CalendarError(f"city_regions: {city} names unknown region {name}")


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
    _validate_regions(data)
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


def _weaker(*names: str) -> str:
    return max(names, key=lambda name: CONFIDENCE.index(name) if name in CONFIDENCE else len(CONFIDENCE))


def event(key: str, region: str | None = None) -> dict | None:
    """An event or a test as one shape {key, months, sources, confidence,
    region}: a test's months are its test months, and `<test>:result` names its
    result months, so a step can wait for a test result like a board result.

    With a region, that region's row replaces the national one by key. A key
    the region lists as a gap stays empty (date not confirmed) rather than
    borrowing the BISE Lahore proxy; any other key falls back to the national
    row, downgraded where the region says its proxy is weaker. Cambridge
    results wait for the IBCC certificate."""
    data = calendar()
    if key.endswith(":result"):
        test = event(key.removesuffix(":result"), region)
        return {**test, "key": key, "months": test["result_months"]} if test and "result_months" in test else None
    area = data.get("regions", {}).get(region) if region else None
    for row in data["events"]:
        if row["key"] != key:
            continue
        if area is not None:
            own = region_events(area).get(key)
            if own is not None:
                found = {"key": key, "months": list(own.get("months") or []), "sources": own["sources"],
                         "confidence": own["confidence"], "region": region}
                return found
            if key in area.get("gaps", ()):
                return {"key": key, "months": [], "sources": [], "confidence": "uncertain", "region": region}
        found = {"key": key, "months": list(row.get("months") or []), "sources": row["sources"],
                 "confidence": row["confidence"], "region": "national"}
        if area is not None:
            found["confidence"] = _weaker(found["confidence"], fallback_confidence(area))
        return found
    for row in data["tests"]:
        if row["key"] == key:
            return {"key": key, "months": list(row.get("test_months") or []), "sources": row["sources"],
                    "confidence": row["confidence"], "result_months": list(row.get("result_months") or []),
                    "region": "national"}
    return None


def fallback_confidence(area: dict) -> str:
    """The grade a national row gets when a region borrows it: the region's own
    national_fallback_confidence, else uncertain (the proxy is BISE Lahore).
    The validator and event() both read it here."""
    return area.get("national_fallback_confidence", "uncertain")


def ibcc_lag(region: str | None) -> dict | None:
    """The IBCC equivalence wait a region's results carry (Cambridge), as
    {months, sources, confidence}, or None."""
    area = calendar().get("regions", {}).get(region) if region else None
    if not area or not area.get("ibcc_lag_months"):
        return None
    return {"months": area["ibcc_lag_months"], "sources": area["ibcc_sources"],
            "confidence": area.get("ibcc_confidence", "uncertain")}


@lru_cache(maxsize=1)
def _board_regions() -> dict:
    """Board choice code -> region, from the catalog's `boards` choices."""
    boards = json.loads(_BOARDS_CATALOG.read_text(encoding="utf-8"))["choices"]["boards"]
    return {board["code"]: board["region"] for board in boards if board.get("region")}


def fallback_region() -> str:
    """The region marked `fallback` in the calendar data (validated: exactly one)."""
    return next(name for name, region in calendar()["regions"].items() if region.get("fallback") is True)


def region_for(education_record: dict | None, city: str | None = None) -> str:
    """The calendar region of a student: the region whose data `levels` name the
    student's level (O/A level: Cambridge), else the
    education record's board (catalog `boards`), else the province of the
    city, else federal. Unknown input never raises; it falls to federal."""
    record = education_record or {}
    catalog = vault_catalog()
    level = catalog.read_education(record.get("qualification_name"), record.get("field_of_study"))[0]
    regions = calendar()["regions"]
    for name, region in regions.items():
        if level and level in (region.get("levels") or ()):
            return name
    board = record.get("board") or (record.get("details") or {}).get("awarding_body")
    code = catalog.choice_code("boards", str(board)) if board else None
    if code in _board_regions():
        return _board_regions()[code]
    region = calendar().get("city_regions", {}).get(" ".join(str(city or "").casefold().split()))
    return region if region and region != "_note" else fallback_region()


def calendar_test(codes) -> dict | None:
    """The calendar test of the first catalog code that has one."""
    for code in codes:
        for row in calendar()["tests"]:
            if code in row.get("codes", ()):
                return row
    return None


def intakes_for(field_key: str, region: str | None = None) -> list[dict]:
    """Intakes open to a field; one that names `regions` applies only there."""
    study = study_fields().get(field_key)
    family = study.family if study else None
    return [row for row in calendar()["intakes"]
            if (field_key in row.get("fields", ()) or (family and family in row.get("families", ())))
            and (not row.get("regions") or region in row["regions"])]


def degree_years(field_key: str) -> int | None:
    years = calendar()["degree_years"].get(field_key)
    return years if field_key not in _DEGREE_META and isinstance(years, int) else None
