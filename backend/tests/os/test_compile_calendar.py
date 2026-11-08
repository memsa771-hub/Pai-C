"""P2-T11: the result-expected step reads an official calendar by its registry id (P2 spec §4.11; master R-20, R-26).
Pure: no database. Fictional route, calendar and student."""

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.os.compiler import compile_plan, needed_calendars, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact
from app.os.playbooks import load_playbook_dir
from app.os.requests.state import StudentState

HERE = Path(__file__).parent
BOOKS = {**load_playbook_dir(HERE / "playbooks"), **load_playbook_dir(HERE / "playbooks" / "needs"),
         **load_playbook_dir(HERE / "playbooks" / "calendar")}
V2, V3 = BOOKS[("pakistan_inter", 2)], BOOKS[("pakistan_inter", 3)]
TODAY = date(2027, 3, 1)
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
OBTAINED = "education.matric.marks_obtained"
RESULT = f"result_expected@fact:{OBTAINED}"
CAL, FIELD = "cal:alpha-results", "result_date"
URL = "https://results.alpha.test/calendar"

pytestmark = pytest.mark.req("R-20")


def contract() -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "ext-1", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "PK", "level": "bachelor",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": "p1", "rank": 1}],
    })


def fact(value, status="confirmed", year=2027) -> Fact:
    return Fact(value=value, quote="q", url=URL, checked_at=CHECKED, intake_year=year, status=status)


MERIT = {("p1", "merit_list_date"): fact({"date": "2027-08-15"})}
DATE = {"date": "2027-04-30", "tz": "Asia/Karachi"}


def build(book=V3, calendar=None, route=None, today=TODAY, **kw):
    return compile_plan(contract(), book, route or {}, MERIT, today, student=StudentState(),
                        calendar_facts=calendar, **kw)


def task(draft, key):
    return next(t for t in draft.tasks if t.instance_key == key)


def keys_of(draft) -> set[str]:
    return {t.instance_key for t in draft.tasks}


def test_the_playbook_names_its_calendar_and_asks_no_route_fact_for_it():
    assert needed_calendars(V3) == {(CAL, FIELD)}
    assert needed_calendars(V2) == set()
    assert "matric_result_date" in needed_fields(V2)[0] and FIELD not in needed_fields(V3)[0]


def test_result_expected_is_dated_from_the_official_calendar():
    d = build(calendar={(CAL, FIELD): fact(DATE)})
    waits = task(d, RESULT)
    assert (waits.task_type, waits.template_key, waits.title) == ("system.milestone", "result_expected",
                                                                  "Matric result expected")
    assert waits.latest_finish == datetime(2027, 4, 30, 23, 59, 59, tzinfo=ZoneInfo("Asia/Karachi"))
    assert waits.fact_refs == (("registry", CAL, FIELD),)  # a change of the calendar fact revises the plan
    assert {(c["source"], c["url"]) for c in waits.citations} == {(f"fact:{CAL}:{FIELD}", URL)}  # names the calendar
    assert not waits.provisional and "confirm_fact@" + CAL + ":" + FIELD not in keys_of(d)
    assert (RESULT, True) in task(d, f"provide@fact:{OBTAINED}:stated").depends_on


def test_the_provide_step_follows_the_calendar_fact_so_a_new_or_moved_date_revises_the_plan():
    provide = f"provide@fact:{OBTAINED}:stated"
    for cal in ({}, {(CAL, FIELD): fact(DATE)}, {(CAL, FIELD): fact({"date": "2027-01-01"})}):  # none, ahead, passed
        assert ("registry", CAL, FIELD) in task(build(calendar=cal), provide).fact_refs
    assert not task(build(V2, route={"matric_result_date": fact(DATE)}), provide).fact_refs  # route asks: as before


def test_an_unconfirmed_calendar_date_is_provisional_and_asks_for_confirmation():
    d = build(calendar={(CAL, FIELD): fact(DATE, status="unconfirmed")})
    assert task(d, RESULT).provisional
    confirm = task(d, f"confirm_fact@{CAL}:{FIELD}")
    assert confirm.fact_refs == (("registry", CAL, FIELD),)  # scope kept: it is not a programme or route fact
    assert confirm.programme_ref is None  # a calendar is not a programme: the check belongs to no programme
    # route and programme checks keep their ref exactly as before
    plain = build(V2, route={"matric_result_date": fact(DATE, status="unconfirmed")})
    assert task(plain, "confirm_fact@pakistan_inter:matric_result_date").programme_ref is None
    assert task(plain, "confirm_fact@pakistan_inter:matric_result_date").fact_refs[0][0] == "route"


def test_a_calendar_date_of_another_year_stays_provisional_r26():
    d = build(calendar={(CAL, FIELD): fact({"date": "2027-04-30"}, year=2026)})
    assert task(d, RESULT).provisional and task(d, f"confirm_fact@{CAL}:{FIELD}")
    firm = build(calendar={(CAL, FIELD): fact({"date": "2027-04-30"}, year=2027)})
    assert not task(firm, RESULT).provisional


def test_after_the_date_or_without_a_date_there_is_no_waiting_step():
    cal = {(CAL, FIELD): fact(DATE)}
    assert RESULT not in keys_of(build(calendar=cal, today=date(2027, 4, 30)))
    later = build(calendar=cal, today=date(2027, 5, 1))
    assert RESULT not in keys_of(later) and f"provide@fact:{OBTAINED}:stated" in keys_of(later)
    assert RESULT not in keys_of(build(calendar={}))
    assert RESULT not in keys_of(build())
    assert RESULT not in keys_of(build(calendar={(CAL, FIELD): fact({"date": "not a date"})}))
    # the calendar of another id is not read
    assert RESULT not in keys_of(build(calendar={("cal:other", FIELD): fact(DATE)}))


def test_a_route_fact_ask_compiles_as_before_and_ignores_calendars():
    route = {"matric_result_date": fact(DATE)}
    plain = build(V2, route=route)
    assert task(plain, RESULT).fact_refs == (("route", "pakistan_inter", "matric_result_date"),)
    assert {c["source"] for c in task(plain, RESULT).citations} == {"fact:matric_result_date"}  # route label unchanged
    with_calendar = build(V2, route=route, calendar={(CAL, FIELD): fact({"date": "2027-12-31"})})
    assert plain.tasks == with_calendar.tasks  # byte-identical: the calendar is not an input of this playbook
    assert RESULT not in keys_of(build(V2, calendar={(CAL, FIELD): fact(DATE)}))  # no route fact, no step


def test_the_calendar_must_look_like_a_registry_id():
    from app.os.playbooks.models import Expected

    with pytest.raises(ValueError):
        Expected(fact="result_date", title="t", calendar="not a registry id")
    assert Expected(fact="result_date", title="t", calendar="cal:a-b_1").calendar == "cal:a-b_1"
