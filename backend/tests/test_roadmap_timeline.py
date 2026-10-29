"""Time to entry and to finish from the coloured steps and the dated calendar
(FOUR_FEATURES_SPEC.md §4.2). Today is frozen; nothing reads the clock."""

from datetime import date

from app.pai_c.roadmap import calendar as cal
from app.pai_c.roadmap.timeline import estimate, next_occurrence
from tests.test_roadmap_steps import TODAY, fsc, route


def basis(time, step):
    return {row["event_key"]: (row["year"], row["month"]) for row in time["basis"] if row["step"] == step}


def test_estimate_pre_eng_current_fsc():
    """Part-2 exam May 2027, ECAT June 2027, Part-2 result September 2027: the
    next fall intake (September 2027) is 11 months from 29 October 2026."""
    steps = route("electrical_engineering", fsc("pre_engineering", status="current"))
    time = estimate(steps, "electrical_engineering", TODAY)
    assert basis(time, "complete_intermediate") == {"hssc_part2_exam": (2027, 5), "hssc_part2_result": (2027, 9)}
    test_key = next(step["key"] for step in steps if step["kind"] == "test")
    assert basis(time, test_key) == {"ecat": (2027, 6), "ecat:result": (2027, 6)}
    assert time["next_intake"]["start_month"] == 9 and time["next_intake"]["year"] == 2027
    assert time["to_entry_months"] == 11
    assert time["to_finish_years"] == round(11 / 12 + 4, 1)
    for row in time["basis"]:
        assert row["source"].startswith("https://") and row["confidence"]


def test_estimate_rolls_to_next_year():
    """In late October, a June test and a May exam are next year's."""
    assert next_occurrence([6], None, TODAY) == (2027, 6)
    assert next_occurrence([5, 6], None, TODAY) == (2027, 5)
    assert next_occurrence([11], None, TODAY) == (2026, 11)
    assert next_occurrence([10], None, TODAY) == (2026, 10)  # this month has not passed yet
    assert next_occurrence([10], (2026, 10), TODAY) == (2027, 10)
    steps = route("electrical_engineering", fsc("pre_engineering", 78))
    time = estimate(steps, "electrical_engineering", TODAY)
    assert [(row["event_key"], row["year"]) for row in time["basis"] if row["step"]] == [
        ("ecat", 2027), ("ecat:result", 2027)]
    # 10, not 11: the calendar carries the FAST-NU fall intake (sourced, uncertain, classes in
    # August), earlier than the September intakes this test used to end on. The NED intake is
    # Sindh-only and does not apply here.
    assert time["to_entry_months"] == 10 and time["next_intake"]["label"] == "Computing/business fall intake"
    assert time["next_intake"]["start_month"] == 8


def test_unknown_event_marks_uncertain():
    """The law route's test step names no calendar test code: that step's date is
    not confirmed and the whole estimate is uncertain."""
    steps = route("law_llb", fsc("pre_engineering", 70))
    time = estimate(steps, "law_llb", TODAY)
    lat = [row for row in time["basis"] if row["step"] and row["step"].startswith("test:")]
    assert lat and lat[0]["month"] is None and lat[0]["event_key"] is None
    assert time["confidence"] == "uncertain"
    # An event whose months were never found is uncertain too.
    steps = route("electrical_engineering", fsc("pre_engineering", 50))
    time = estimate(steps, "electrical_engineering", TODAY)
    improve = {row["event_key"]: row["month"] for row in time["basis"] if row["step"] == "marks"}
    assert improve["hssc_supplementary_result"] is None and time["confidence"] == "uncertain"


def test_finish_adds_degree_years():
    steps = route("mbbs", fsc("pre_medical", status="current"))
    time = estimate(steps, "mbbs", TODAY)
    # MDCAT September 2027, result October 2027; MBBS classes start in February.
    assert time["next_intake"]["year"] == 2028 and time["next_intake"]["start_month"] == 2
    assert time["to_entry_months"] == 16
    assert time["degree_years"] == 5 and time["to_finish_years"] == round(16 / 12 + 5, 1)
    bds = estimate(route("bds", fsc("pre_medical", status="current")), "bds", TODAY)
    assert bds["degree_years"] == 4  # the admission rule's per-field years win


def test_never_negative_and_done_steps_wait_for_nothing():
    steps = route("electrical_engineering", fsc("pre_engineering", 78))
    for step in steps:
        step["status"] = "done"
    time = estimate(steps, "electrical_engineering", date(2027, 9, 15))
    assert time["to_entry_months"] == 0 and time["next_intake"]["year"] == 2027


def test_karachi_board_student_uses_sindh_dates():
    """A matric student of a Sindh board waits for the Sindh result month (July),
    not the Punjab proxy (August); the Sindh exam months nobody found stay
    'date not confirmed'."""
    matric = {"qualification_name": "matric", "academic_status": "current", "board": "bise_karachi"}
    region = cal.region_for(matric, "Karachi")
    assert region == "sindh"
    steps = route("electrical_engineering", matric)
    time = estimate(steps, "electrical_engineering", TODAY, region)
    rows = {row["event_key"]: row for row in time["basis"] if row["step"] == "complete_intermediate"}
    assert (rows["ssc_annual_result"]["year"], rows["ssc_annual_result"]["month"]) == (2027, 7)
    assert rows["ssc_annual_result"]["region"] == "sindh"
    assert rows["hssc_part1_exam"]["month"] is None and time["confidence"] == "uncertain"
    national = estimate(steps, "electrical_engineering", TODAY)
    assert {r["event_key"]: r["month"] for r in national["basis"]}["ssc_annual_result"] == 8


def test_a_level_student_gets_cambridge_rows_and_an_ibcc_entry():
    alevel = {"qualification_name": "a_level", "academic_status": "current", "field_of_study": "pre_engineering"}
    region = cal.region_for(alevel, "Lahore")
    assert region == "cambridge"
    steps = route("electrical_engineering", alevel)
    time = estimate(steps, "electrical_engineering", TODAY, region)
    rows = {row["event_key"]: row for row in time["basis"] if row["step"] == "complete_intermediate"}
    for key, month in (("alevel_june_series", 5), ("alevel_june_result", 8), ("ibcc_equivalence", 9)):
        assert (rows[key]["year"], rows[key]["month"], rows[key]["region"]) == (2027, month, "cambridge"), key
    assert rows["ibcc_equivalence"]["source"].startswith("https://ibcc.edu.pk")
    assert rows["ibcc_equivalence"]["confidence"] == "official"
    assert {row["region"] for row in time["basis"] if (row["event_key"] or "").startswith(("alevel_", "ibcc"))} == {
        "cambridge"}
    plain = estimate(steps, "electrical_engineering", TODAY)
    assert "ibcc_equivalence" not in {r["event_key"] for r in plain["basis"]}


def test_region_fallback_federal():
    """An unknown board and a city outside Pakistan: federal region, estimate
    still returns, uncertain, no crash."""
    record = fsc("pre_engineering", status="current", board="Mars board")
    region = cal.region_for(record, "Paris")
    assert region == "federal_fbise"
    time = estimate(route("electrical_engineering", record), "electrical_engineering", TODAY, region)
    assert time["confidence"] == "uncertain"
    by_event = {row["event_key"]: row for row in time["basis"] if row["step"] == "complete_intermediate"}
    assert by_event["hssc_part2_exam"]["region"] == "national"  # no federal row: borrowed, not federal
    assert by_event["hssc_part2_exam"]["confidence"] == "uncertain"
    assert by_event["hssc_part2_result"]["region"] == "federal_fbise"


def test_student_borrowing_a_national_row_is_uncertain():
    """AKU-EB has few rows of its own: the rest is the national proxy, uncertain."""
    matric = {"qualification_name": "matric", "academic_status": "current", "board": "aga_khan"}
    time = estimate(route("electrical_engineering", matric), "electrical_engineering", TODAY, "aku_eb")
    rows = {row["event_key"]: row for row in time["basis"] if row["step"] == "complete_intermediate"}
    assert rows["ssc_annual_result"]["region"] == "aku_eb"
    assert rows["hssc_part1_result"]["region"] == "national" and rows["hssc_part1_result"]["confidence"] == "uncertain"
    sindh = estimate(route("electrical_engineering", matric), "electrical_engineering", TODAY, "sindh")
    gap = {r["event_key"]: r for r in sindh["basis"] if r["step"] == "complete_intermediate"}["hssc_part2_exam"]
    assert gap["region"] == "sindh" and gap["month"] is None


def test_confidence_is_the_weakest_used_in_a_region():
    record = fsc("pre_engineering", status="current")
    time = estimate(route("electrical_engineering", record), "electrical_engineering", TODAY, "punjab")
    assert time["confidence"] == "secondary"
    assert any(row["region"] == "punjab" for row in time["basis"])
