"""P2-T11: calendars as registry rows with cycle-bound date facts (P2 spec §4.11; master R-20, R-26, R-33).
Fixture calendars only: invented bodies and dates on `.test` domains."""

from dataclasses import replace
from datetime import date

import pytest

from app.os.knowledge.fact_classes import is_high_stakes
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from app.os.registry.calendars import (
    CalendarError,
    calendar_dates,
    calendar_types,
    record_calendar,
    record_calendar_date,
)
from app.os.registry.model import RegistryEntry

from .helpers import AT, child, inst, olist, store

pytestmark = pytest.mark.req("R-33")
URL = "https://results.alpha.test/calendar"


def calendar_entry(slug="alpha-results", parent="body:alpha-board", **kw) -> RegistryEntry:
    return RegistryEntry(entity_id=f"cal:{slug}", kind="calendar", name="Alpha board result calendar", parent_id=parent,
                         source_url=URL, quote="Results are announced as below", checked_at=AT, **kw)


@pytest.fixture
def world(engine, clean):
    s = store(engine)
    s.record(olist(), cause="import")
    s.record(child("admission_body", "body", "alpha-board", None, region="national"), cause="import")
    s.record(inst("one"), cause="import")
    return s, SqlKnowledge(engine, "pai")


def test_the_vocabulary_names_the_types_their_date_fields_and_classes():
    types = calendar_types()
    assert {"exam", "result", "admission"} <= set(types)
    assert "result_date" in types["result"].fields and types["result"].fields["result_date"] == "schedule_date"
    assert is_high_stakes(types["result"].fields["result_date"])  # dates a student plans on are high-stakes (R-25)
    assert all(types[t].fields for t in types)


def test_record_a_calendar_row_with_its_type(world):
    s, _ = world
    rec = record_calendar(s, calendar_entry(), "result", cause="import", cause_ref="imp-1")
    assert rec.action == "insert"
    e = s.get("cal:alpha-results")
    assert (e.kind, e.parent_id, e.attrs["calendar_type"]) == ("calendar", "body:alpha-board", "result")
    assert record_calendar(s, calendar_entry(), "result", cause="import").action == "unchanged"
    with pytest.raises(CalendarError, match="type"):
        record_calendar(s, calendar_entry("other"), "weather", cause="import")
    with pytest.raises(CalendarError, match="calendar"):
        record_calendar(s, replace(inst("two"), attrs={}), "result", cause="import")
    with pytest.raises(CalendarError, match="type"):  # a calendar keeps its type
        record_calendar(s, calendar_entry(), "exam", cause="import")


def test_a_calendar_may_belong_to_an_institution(world):
    s, _ = world
    record_calendar(s, calendar_entry("inst-cal", parent="inst:one"), "admission", cause="import")
    assert s.get("cal:inst-cal").parent_id == "inst:one"


def test_record_a_date_fact_per_intake(world):
    s, k = world
    record_calendar(s, calendar_entry(), "result", cause="import")
    fid = record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 20), tz="Etc/UTC", url=URL,
                               quote="Result: 20 May", checked_at=AT, intake_year=2031, intake_term="main",
                               cause="import", cause_ref="imp-1")
    scope, ref, field, fact = k.get(fid)
    assert (scope, ref, field) == ("registry", "cal:alpha-results", "result_date")
    assert fact.value == {"date": "2031-05-20", "tz": "Etc/UTC"}
    assert (fact.intake_year, fact.intake_term, fact.status, fact.fact_class) == (2031, "main", "confirmed",
                                                                                   "schedule_date")
    assert k.revisions(fid)[0].cause_ref == "imp-1"
    # another intake is another fact; the same intake again replaces the date (a revision records it)
    record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2032, 5, 18), url=URL, quote="q",
                         checked_at=AT, intake_year=2032, intake_term="main", cause="import")
    again = record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 22), url=URL, quote="q2",
                                 checked_at=AT, intake_year=2031, intake_term="main", cause="import")
    assert again == fid and [r.action for r in k.revisions(fid)] == ["insert", "change"]


def test_a_date_fact_needs_a_calendar_a_field_of_its_type_and_a_source(world):
    s, k = world
    record_calendar(s, calendar_entry(), "result", cause="import")
    base = {"url": URL, "quote": "q", "checked_at": AT, "intake_year": 2031, "intake_term": "main", "cause": "import"}
    with pytest.raises(CalendarError, match="not a calendar"):
        record_calendar_date(s, k, "inst:one", "result_date", date(2031, 5, 20), **base)
    with pytest.raises(CalendarError, match="not in the registry"):
        record_calendar_date(s, k, "cal:ghost", "result_date", date(2031, 5, 20), **base)
    with pytest.raises(CalendarError, match="field"):  # an exam date does not belong to a result calendar
        record_calendar_date(s, k, "cal:alpha-results", "exam_date", date(2031, 5, 20), **base)
    with pytest.raises(CalendarError, match="timezone"):
        record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 20), tz="Mars/Base", **base)
    with pytest.raises(ValueError):  # a confirmed fact needs its quote (invariant 3)
        record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 20), **{**base, "quote": ""})
    with pytest.raises(ValueError, match="verified"):  # verified only through review
        record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 20), status="verified", **base)
    unconfirmed = record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 20), status="unconfirmed",
                                       **{**base, "quote": ""})
    assert k.get(unconfirmed)[3].status == "unconfirmed"


def test_read_the_dates_of_a_calendar(world):
    s, k = world
    record_calendar(s, calendar_entry(), "result", cause="import")
    record_calendar(s, calendar_entry("alpha-exams", "body:alpha-board"), "exam", cause="import")
    base = {"url": URL, "quote": "q", "checked_at": AT, "intake_term": "main", "cause": "import"}
    record_calendar_date(s, k, "cal:alpha-results", "result_date", date(2031, 5, 20), intake_year=2031, **base)
    record_calendar_date(s, k, "cal:alpha-exams", "exam_date", date(2031, 3, 2), intake_year=2031, **base)
    got = calendar_dates(k, ["cal:alpha-results", "cal:alpha-exams"], 2031)
    assert {key: f.value["date"] for key, f in got.items()} == {("cal:alpha-results", "result_date"): "2031-05-20",
                                                                ("cal:alpha-exams", "exam_date"): "2031-03-02"}
    assert calendar_dates(k, ["cal:alpha-results"], 2032) == {}
    assert isinstance(next(iter(got.values())), Fact)
