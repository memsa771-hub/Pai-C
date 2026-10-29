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
    (lambda d: d["regions"]["federal_fbise"].pop("fallback"), "fallback"),
    (lambda d: d["regions"]["punjab"].update(fallback=True), "fallback"),
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


def region_rows():
    return [(name, key, row) for name, region in cal.calendar()["regions"].items()
            for key, row in cal.region_events(region).items()]


def test_every_region_event_has_an_https_source_and_a_confidence():
    rows = region_rows()
    assert rows and {name for name, _, _ in rows} >= {"punjab", "sindh", "kp", "balochistan", "federal_fbise",
                                                       "aku_eb", "ajk"}
    for name, key, row in rows:
        assert any(url.startswith("https://") for url in row["sources"]), (name, key)
        assert row["confidence"] in cal.CONFIDENCE, (name, key)


def test_region_months_are_1_to_12():
    months = [m for _, _, row in region_rows() for m in row["months"]]
    assert months and all(isinstance(m, int) and 1 <= m <= 12 for m in months)


def test_region_gaps_stay_empty_not_invented():
    sindh, gb = cal.calendar()["regions"]["sindh"], cal.calendar()["regions"]["gilgit_baltistan"]
    assert cal.region_events(gb) == {}
    assert "hssc_part2_exam" in sindh["gaps"] and "hssc_part2_exam" not in cal.region_events(sindh)
    assert cal.event("hssc_part2_exam", "sindh")["months"] == []
    assert cal.event("hssc_part1_exam", "sindh")["months"] == []
    assert cal.event("ssc_annual_result", "sindh")["months"] == [7]


def test_region_event_overrides_national_and_falls_back():
    assert cal.event("ssc_annual_result")["months"] == [8]
    kp = cal.event("hssc_part1_exam", "kp")
    assert kp["months"] == [5] and kp["region"] == "kp" and kp["confidence"] == "secondary"
    proxy = cal.event("hssc_part2_exam", "federal_fbise")  # no federal row: national proxy, weakened
    assert proxy["region"] == "national" and proxy["confidence"] == "uncertain"
    assert cal.event("hssc_part2_exam", "punjab")["region"] == "punjab"


def test_region_for_board_city_and_fallback():
    karachi = {"qualification_name": "fsc", "details": {"awarding_body": "Karachi board"}}
    assert cal.region_for({"qualification_name": "fsc", "board": "bise_karachi"}) == "sindh"
    assert cal.region_for({"qualification_name": "fsc", "board": "Lahore board"}, "Karachi") == "punjab"
    assert cal.region_for({"qualification_name": "fsc", "details": {"awarding_body": "bise_peshawar"}}) == "kp"
    assert cal.region_for({"qualification_name": "fsc", "board": "federal board"}) == "federal_fbise"
    assert cal.region_for({"qualification_name": "fsc", "board": "aga khan"}) == "aku_eb"
    assert cal.region_for({"qualification_name": "fsc"}, " Quetta ") == "balochistan"
    assert cal.region_for(karachi, "Lahore") == "sindh"  # the board wins over the city
    assert cal.region_for({"qualification_name": "a level", "board": "bise_lahore"}, "Lahore") == "cambridge"
    assert cal.region_for({"qualification_name": "o_level"}, None) == "cambridge"


def test_region_fallback_federal():
    assert cal.region_for(None, None) == "federal_fbise"
    assert cal.region_for({"qualification_name": "fsc", "board": "Mars board"}, "Paris") == "federal_fbise"


def test_every_catalog_board_names_a_calendar_region():
    from app.pai_c.memory import vault_catalog
    regions = cal.calendar()["regions"]
    for board in vault_catalog().choices("boards"):
        assert cal.region_for({"qualification_name": "fsc", "board": board.code}) in regions
    assert set(cal._board_regions()) == {b.code for b in vault_catalog().choices("boards")}


def test_region_cambridge_has_its_own_rows_and_an_explicit_ibcc_lag():
    cambridge = cal.calendar()["regions"]["cambridge"]
    assert {"alevel_june_series", "alevel_june_result", "alevel_nov_series",
            "alevel_nov_result"} <= set(cal.region_events(cambridge))
    result = cal.event("alevel_june_result", "cambridge")
    assert result["region"] == "cambridge" and result["months"] == [8]  # unshifted
    lag = cal.ibcc_lag("cambridge")
    assert lag["months"] == 1 and lag["sources"][0].startswith("https://") and lag["confidence"] == "official"
    assert cal.ibcc_lag("sindh") is None


def test_borrowed_national_rows_are_uncertain_in_every_non_punjab_region():
    """A region without national_fallback_confidence is treated as uncertain, as
    the validator does; Punjab is the proxy itself and keeps the national grade."""
    national = cal.event("hssc_part1_result")
    assert national["confidence"] == "official"
    for region in ("sindh", "kp", "balochistan", "federal_fbise", "aku_eb", "ajk", "gilgit_baltistan", "cambridge"):
        row = cal.event("dae_annual_result", region)
        assert row["region"] == "national" and row["confidence"] == "uncertain", region
    assert cal.event("hssc_supplementary_result", "sindh")["confidence"] == "uncertain"
    assert cal.fallback_confidence({}) == "uncertain"
    assert cal.event("hssc_part1_result", "cambridge")["confidence"] == "uncertain"
    assert cal.event("ssc_annual_exam", "punjab")["region"] == "punjab"


def test_regional_intake_applies_only_to_its_region():
    keys = lambda region: {row["key"] for row in cal.intakes_for("electrical_engineering", region)}
    assert "ned_fall" in keys("sindh") and "ned_fall" not in keys("punjab") and "ned_fall" not in keys(None)


def test_region_names_come_from_the_calendar_data():
    """No region name in code: the fallback region and the level-routed region are data."""
    import inspect
    source = inspect.getsource(cal)
    assert "federal_fbise" not in source and '"cambridge"' not in source
    assert cal.fallback_region() == "federal_fbise"
    assert cal.calendar()["regions"]["cambridge"]["levels"] == ["o_level", "a_level"]
