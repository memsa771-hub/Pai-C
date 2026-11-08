"""P2-T11: calendars arrive through the import: the row is recorded with its type, each date goes through the calendar's
own path and tells the plans that use it, so a re-import that moves a date moves the plan (row 6.10, P2 spec §4.11).
Fictional board, route and student; no real date."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import models
from app.os.kernel import Kernel
from app.os.knowledge.sheets.importer import plan_hook, run_import
from app.os.knowledge.sheets.undo import undo_import
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import load_playbook_dir
from app.os.registry.store import RegistryStore
from app.os.requests.state import StudentState
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.test_compile_needs import OBTAINED, contract

from .helpers import COUNTRY, deps, fact, inst, load_list, workbook

BOOKS = load_playbook_dir(Path(__file__).parents[1] / "playbooks" / "calendar")
RESULT = f"result_expected@fact:{OBTAINED}"
CAL = "cal:alpha-results"

pytestmark = [pytest.mark.req("R-20"), pytest.mark.req("R-33")]


class Clock:
    day = date(2027, 3, 1)

    def __call__(self):
        return self.day


def rows(**kw):
    body = inst(1, ctype="admission_body", source_url="https://board.alpha.test/about", timezone="Asia/Karachi")
    body.update(inst_id="ALPHA-BOARD", name="Alpha board")
    cal = inst(2, ctype="result_calendar", source_url="https://board.alpha.test/results", parent_id="ALPHA-BOARD", **kw)
    cal.update(inst_id="ALPHA-RESULTS", name="Alpha board result calendar")
    return [body, cal]


def date_fact(day: str, **kw):
    return fact(1, "ALPHA-RESULTS", field_="result_date", value=day, intake="Winter 2027", **kw)


def task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).first()


@pytest.fixture
def world(engine, clean, monkeypatch, tmp_path):
    monkeypatch.setattr("app.os.service.state.build", lambda plans, student_ref, *a, **k: StudentState())
    load_list(engine)
    kernel, kb = Kernel(engine, "pai"), SqlKnowledge(engine, "pai")
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), kernel, kb, dict(BOOKS), today=Clock())
    d = deps(engine, on_fact_change=plan_hook(svc, kernel))
    return svc, d, tmp_path


def do_import(d, tmp_path, name, institutions, facts):
    path = workbook(tmp_path, institutions, facts, name=name)
    return run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")


def test_the_calendar_row_and_its_date_arrive_through_the_calendar_paths(engine, world):
    _, d, tmp = world
    res = do_import(d, tmp, "a.xlsx", rows(), [date_fact("2031-05-20")])
    assert [r.reason for r in res.rows if r.sheet == "Facts"] == ["both_checks"]
    cal = RegistryStore(engine, "pai").get(CAL)
    assert (cal.kind, cal.parent_id, cal.attrs["calendar_type"], cal.attrs["trust"]) == (
        "calendar", "body:alpha-board", "result", "verified")
    f = d.knowledge.registry_facts([CAL], ["result_date"], 2027, intake_term="winter")[(CAL, "result_date")]
    assert f.value == {"date": "2031-05-20", "tz": "Asia/Karachi"} and f.status == "verified"
    assert f.fact_class == "schedule_date" and f.intake_term == "winter"  # the class comes from the calendar's type


def test_a_wrong_field_for_the_calendars_type_is_rejected_not_loaded(engine, world):
    _, d, tmp = world
    res = do_import(d, tmp, "a.xlsx", rows(), [fact(1, "ALPHA-RESULTS", field_="exam_date", value="2031-05-20",
                                                    intake="Winter 2027")])
    assert [r.reason for r in res.rows if r.sheet == "Facts"] == ["field_not_in_calendar"]
    assert d.knowledge.registry_facts([CAL], ["exam_date"], 2027) == {}


def test_a_reimport_that_moves_the_result_date_moves_the_plan(engine, world):
    svc, d, tmp = world
    plan = svc.start_plan(contract(), with_needs=True).plan_id
    assert task(engine, plan, RESULT) is None  # no calendar yet
    # first import: the date arrives and the plan, which already follows the calendar, gets its waiting step
    do_import(d, tmp, "a.xlsx", rows(), [date_fact("2027-04-30")])
    waits = task(engine, plan, RESULT)
    assert waits is not None and waits.due_at.date() == date(2027, 4, 30) and not waits.provisional
    assert waits.fact_refs == [["registry", CAL, "result_date"]]
    # the board moves the date; the corrected batch is another file: the plan follows without anyone recompiling it
    do_import(d, tmp, "b.xlsx", rows(), [date_fact("2027-05-12")])
    assert task(engine, plan, RESULT).due_at.date() == date(2027, 5, 12)
    f = d.knowledge.registry_facts([CAL], ["result_date"], 2027, intake_term="winter")[(CAL, "result_date")]
    assert f.value["date"] == "2027-05-12" and f.status == "verified"
    assert next(r.action for r in d.knowledge.revisions(f.id)) == "insert"


def test_without_a_hook_the_import_still_loads_and_the_plan_waits_for_its_next_revision(engine, world):
    svc, _, tmp = world
    plain = deps(engine)  # no on_fact_change
    plan = svc.start_plan(contract(), with_needs=True).plan_id
    do_import(plain, tmp, "a.xlsx", rows(), [date_fact("2027-04-30")])
    assert task(engine, plan, RESULT) is None  # not told; this is why the API and the CLI always pass the hook
    svc.recompile(plan, "manual")
    assert task(engine, plan, RESULT).due_at.date() == date(2027, 4, 30)


def test_undoing_the_import_closes_the_calendar_and_withdraws_its_dates(engine, world):
    _, d, tmp = world
    res = do_import(d, tmp, "a.xlsx", rows(), [date_fact("2031-05-20")])
    r = undo_import(engine, "pai", res.import_id, actor="admin")
    assert r.facts == 1 and r.registry == 2
    assert RegistryStore(engine, "pai").get(CAL).status == "closed"
    f = d.knowledge.registry_facts([CAL], ["result_date"], 2027, intake_term="winter")[(CAL, "result_date")]
    assert f.status == "stale" and f.value is None
