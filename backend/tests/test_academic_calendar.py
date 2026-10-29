"""The dated academic calendar the time estimate reads (FOUR_FEATURES_SPEC.md
§4.2): every date is sourced and graded, months are real months, and degree
lengths name study fields."""

import copy

import pytest

from app.pai_c.memory import vault_catalog
from app.pai_c.paths.fields import study_fields
from app.pai_c.roadmap import calendar as cal
from app.pai_c.roadmap.engine import roadmap_policy
from app.pai_c.roadmap.rules import _data as admission_data


def entries():
    data = cal.calendar()
    return [("event", row) for row in data["events"]] + [("intake", row) for row in data["intakes"]] + [
        ("test", row) for row in data["tests"]]


def test_every_entry_has_an_https_source_and_a_confidence():
    for kind, row in entries():
        assert any(url.startswith("https://") for url in row["sources"]), (kind, row["key"])
        assert row["confidence"] in cal.CONFIDENCE, (kind, row["key"])
    assert cal.calendar()["as_of"]


def test_months_are_1_to_12():
    data = cal.calendar()
    months = [m for row in data["events"] for m in row["months"]]
    months += [m for row in data["tests"] for name in ("register_months", "test_months", "result_months")
               for m in row[name]]
    months += [m for row in data["intakes"] for m in row["apply_months"] + row.get("merit_list_months", [])]
    months += [row["classes_start_month"] for row in data["intakes"] if row["classes_start_month"] is not None]
    assert months and all(isinstance(m, int) and 1 <= m <= 12 for m in months)


def test_degree_years_keys_are_study_fields():
    years = {k: v for k, v in cal.calendar()["degree_years"].items() if k not in {"_note", "sources", "confidence"}}
    assert years and set(years) <= set(study_fields())
    assert cal.degree_years("mbbs") == 5 and cal.degree_years("sources") is None


def test_gaps_stay_empty_not_invented():
    data = cal.calendar()
    events = {row["key"]: row for row in data["events"]}
    assert events["hssc_supplementary_result"]["months"] == []
    assert events["dae_annual_result"]["months"] == []
    uet = next(row for row in data["intakes"] if row["key"] == "engineering_fall_uet")
    assert uet["classes_start_month"] is None


@pytest.mark.parametrize("break_it, message", [
    (lambda d: d["events"][0].update(sources=["http://example.com"]), "https source"),
    (lambda d: d["events"][0].update(confidence="likely"), "confidence"),
    (lambda d: d["tests"][0].update(test_months=[13]), "1-12"),
    (lambda d: d["intakes"][0].update(apply_months=[0]), "1-12"),
    (lambda d: d["degree_years"].update(bs=4), "study field"),
])
def test_validator_refuses_a_bad_file(break_it, message):
    data = copy.deepcopy(cal.calendar())
    break_it(data)
    with pytest.raises(cal.CalendarError, match=message):
        cal.validate(data)


def test_policy_and_rules_name_calendar_and_catalog_keys():
    """Every event the timeline policy chains is in the calendar, intakes name
    real families or fields, and test codes are catalog tests."""
    keys = {row["key"] for row in cal.calendar()["events"]}
    timeline = roadmap_policy()["timeline"]
    for chain in [*timeline["finish"].values(), *timeline["improve"].values()]:
        assert set(chain["chain"]) | {chain["result"]} <= keys
    families = {field.family for field in study_fields().values()}
    for intake in cal.calendar()["intakes"]:
        assert set(intake["families"]) <= families and set(intake.get("fields", [])) <= set(study_fields())
        assert intake["label"]
    tests = {choice.code for choice in vault_catalog().choices("tests")}
    for row in cal.calendar()["tests"]:
        assert row["codes"] and set(row["codes"]) <= tests
    for rule in admission_data()["rules"]:
        for test in rule.get("entry_tests", []):
            assert set(test.get("codes", [])) <= tests
