"""P2-T11, row 6.20 (data not available yet, result due): the result-expected step is dated from an official calendar of
the registry, then the provide step; when the calendar's date arrives, moves or passes the plan follows (row 6.10 path).
Real service, kernel and Postgres. Fictional board, calendar, route and student; no real date."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import models
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.changes import after_fact_change
from app.os.playbooks import load_playbook_dir
from app.os.registry.calendars import record_calendar, record_calendar_date
from app.os.registry.model import RegistryEntry
from app.os.registry.store import RegistryStore
from app.os.requests.state import StudentState
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.registry.helpers import AT, child, olist
from tests.os.test_compile_needs import OBTAINED, contract

BOOKS = load_playbook_dir(Path(__file__).parent / "playbooks" / "calendar")
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
CAL, FIELD = "cal:alpha-results", "result_date"
RESULT = f"result_expected@fact:{OBTAINED}"
PROVIDE = f"provide@fact:{OBTAINED}:stated"
URL = "https://results.alpha.test/calendar"

pytestmark = [pytest.mark.req("R-20"), pytest.mark.req("R-26")]


class Clock:
    day = date(2027, 3, 1)

    def __call__(self):
        return self.day


@pytest.fixture
def world(engine, clean, monkeypatch):
    monkeypatch.setattr("app.os.service.state.build", lambda plans, student_ref, *a, **k: StudentState())
    clock = Clock()
    kernel, kb = Kernel(engine, "pai"), SqlKnowledge(engine, "pai")
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), kernel, kb, dict(BOOKS), today=clock)
    registry = RegistryStore(engine, "pai")
    registry.record(olist(), cause="import")
    registry.record(child("admission_body", "body", "alpha-board", None, region="national"), cause="import")
    record_calendar(registry, RegistryEntry(
        entity_id=CAL, kind="calendar", name="Alpha board result calendar", parent_id="body:alpha-board",
        source_url=URL, quote="Results are announced as below", checked_at=AT), "result", cause="import")
    kb.upsert("programme", "p1", "merit_list_date", Fact({"date": "2027-08-15"}, "q", URL, CHECKED, 2027, "confirmed"))
    return svc, kb, kernel, registry, clock


def date_fact(registry, kb, day: date, status="confirmed", year=2027) -> int:
    return record_calendar_date(registry, kb, CAL, FIELD, day, tz="Asia/Karachi", url=URL,
                                quote="Result day" if status == "confirmed" else "", checked_at=CHECKED,
                                intake_year=year, intake_term="winter", status=status, cause="import")


def task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).first()


def test_6_20_the_result_step_follows_the_official_calendar(engine, world):
    svc, kb, kernel, registry, clock = world
    ref = svc.start_plan(contract(), with_needs=True)
    plan = ref.plan_id
    # no date published yet: only the provide step, which already follows the calendar fact
    assert task(engine, plan, RESULT) is None and task(engine, plan, PROVIDE).state == "waiting_student"
    assert task(engine, plan, PROVIDE).fact_refs == [["registry", CAL, FIELD]]

    # the date arrives (unconfirmed first): the plan gets a waiting step dated from the calendar, provisional, with a check
    fid = date_fact(registry, kb, date(2027, 4, 30), status="unconfirmed")
    assert after_fact_change(svc, kernel, "registry", CAL, FIELD, fid, "unconfirmed", 2027, complete=False) == [plan]
    waits = task(engine, plan, RESULT)
    assert waits.state == "blocked" and waits.blocked_reason == f"result_expected:{OBTAINED}"
    assert waits.due_at.date() == date(2027, 4, 30) and waits.provisional
    assert task(engine, plan, f"confirm_fact@{CAL}:{FIELD}").fact_refs == [["registry", CAL, FIELD]]
    draft = svc.compile(contract(), BOOKS[("pakistan_inter", 3)], plan)  # the provide step now waits for the result step
    assert (RESULT, True) in next(t for t in draft.tasks if t.instance_key == PROVIDE).depends_on

    # a checker confirms it: the step is firm and cites the calendar page
    date_fact(registry, kb, date(2027, 4, 30))
    assert after_fact_change(svc, kernel, "registry", CAL, FIELD, fid, "confirmed", 2027) == [plan]
    waits = task(engine, plan, RESULT)
    assert not waits.provisional and {c["url"] for c in waits.citations} == {URL}

    # the board moves the date: the plan follows (row 6.10)
    date_fact(registry, kb, date(2027, 5, 12))
    assert after_fact_change(svc, kernel, "registry", CAL, FIELD, fid, "confirmed", 2027) == [plan]
    assert task(engine, plan, RESULT).due_at.date() == date(2027, 5, 12)

    # the day passes: the waiting step is gone and the student is asked for the marks
    clock.day = date(2027, 5, 13)
    svc.recompile(plan, "clock")
    gone = task(engine, plan, RESULT)
    assert gone is None or gone.state in ("done", "cancelled", "skipped")
    draft = svc.compile(contract(), BOOKS[("pakistan_inter", 3)], plan)
    assert RESULT not in {t.instance_key for t in draft.tasks}
    assert (RESULT, True) not in next(t for t in draft.tasks if t.instance_key == PROVIDE).depends_on
    assert task(engine, plan, PROVIDE).state == "waiting_student"


def test_a_calendar_fact_of_another_intake_does_not_date_this_plan(engine, world):
    svc, kb, _, registry, _ = world
    date_fact(registry, kb, date(2026, 4, 30), year=2026)  # last year's result day
    ref = svc.start_plan(contract(), with_needs=True)
    assert task(engine, ref.plan_id, RESULT) is None  # strict read: no registered intake, no previous-year fallback


def test_the_route_fact_playbooks_are_untouched(engine, clean):
    from tests.os.test_compile_needs import BOOKS as OLD

    kb = SqlKnowledge(engine, "pai")
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb,
                      {("pakistan_inter", 2): OLD[("pakistan_inter", 2)]}, today=Clock())
    assert svc.compile(contract(), OLD[("pakistan_inter", 2)]).tasks is not None  # no registry read, no error


def test_r26_while_the_intake_is_open_last_years_calendar_date_is_used_labelled_and_provisional(engine, world):
    from app.os.intakes.store import IntakeStore

    svc, kb, _, registry, clock = world
    clock.day = date(2026, 3, 1)
    date_fact(registry, kb, date(2026, 4, 30), year=2026)  # last year's result day (a confirmed fact)
    IntakeStore(engine, "pai").create("punjab", "intermediate", "winter", 2027, state="open")  # no fact for 2027 yet
    ref = svc.start_plan(contract(), with_needs=True)
    waits = task(engine, ref.plan_id, RESULT)
    assert waits.due_at.date() == date(2026, 4, 30) and waits.provisional  # R-26: the other year is never firm
    assert task(engine, ref.plan_id, f"confirm_fact@{CAL}:{FIELD}") is not None
    date_fact(registry, kb, date(2027, 4, 29), year=2027)  # this intake's own date arrives and wins
    clock.day = date(2027, 3, 1)
    svc.recompile(ref.plan_id, "fact_changed")
    waits = task(engine, ref.plan_id, RESULT)
    assert waits.due_at.date() == date(2027, 4, 29) and not waits.provisional
