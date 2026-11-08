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


# --- every fact an import writes, and every fact an undo changes back, tells the plans (row 6.10) --------------------


def programme_rows():
    from .helpers import prog

    return [inst(3)], [prog(1, "T-INST-003", programme_id="p1")]


def merit_fact(day: str):
    return fact(7, "p1", field_="merit_list_date", value=day, intake="Winter 2027")


def import_programme_date(d, tmp, name, day):
    institutions, programmes = programme_rows()
    path = workbook(tmp, institutions, [merit_fact(day)], programmes, name=name)
    return run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")


def test_a_programme_fact_written_by_an_import_moves_the_plan_that_uses_it(engine, world):
    svc, d, tmp = world
    plan = svc.start_plan(contract(), with_needs=True).plan_id
    first = task(engine, plan, "merit_list@p1")
    import_programme_date(d, tmp, "a.xlsx", "2027-08-15")
    after_first = task(engine, plan, "merit_list@p1")
    assert after_first.due_at != first.due_at  # the date arrived and the plan took it without anyone recompiling it
    import_programme_date(d, tmp, "b.xlsx", "2027-09-20")  # the corrected batch moves the date
    after_second = task(engine, plan, "merit_list@p1")
    assert after_second.due_at > after_first.due_at and after_second.due_at.date() >= date(2027, 9, 20)


def test_the_hook_is_called_for_every_scope_after_the_fact_is_stored(engine, world):
    _, d, tmp = world
    seen = []

    def hook(scope, ref, field, fid, status, year):  # the fact is already in the database when the hook runs
        seen.append((scope, ref, field, status, year, d.knowledge.get(fid)[3].status))

    d.on_fact_change = hook
    institutions, programmes = programme_rows()
    path = workbook(tmp, [*institutions, *rows()], [merit_fact("2027-08-15"), date_fact("2031-05-20")], programmes)
    run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    assert sorted(seen) == [
        ("programme", "p1", "merit_list_date", "verified", 2027, "verified"),
        ("programme", "p1", "seats_open_merit", "verified", 2026, "verified"),
        ("registry", CAL, "result_date", "verified", 2027, "verified"),
    ]


def test_an_undo_tells_the_plans_for_each_fact_it_changes_back(engine, world):
    from app.os.knowledge.sheets.undo import undo_import

    svc, d, tmp = world
    plan = svc.start_plan(contract(), with_needs=True).plan_id
    base = task(engine, plan, "merit_list@p1").due_at
    res = import_programme_date(d, tmp, "a.xlsx", "2027-08-15")
    moved = task(engine, plan, "merit_list@p1").due_at
    assert moved != base
    seen = []
    plans_hook = plan_hook(svc, svc.kernel)

    def hook(scope, ref, field, fid, status, year):
        seen.append((scope, ref, field, status, year))
        plans_hook(scope, ref, field, fid, status, year)

    undo_import(engine, "pai", res.import_id, actor="admin", on_fact_change=hook)
    assert sorted(seen) == [("programme", "p1", "merit_list_date", "stale", 2027),
                            ("programme", "p1", "seats_open_merit", "stale", 2026)]
    assert task(engine, plan, "merit_list@p1").due_at != moved  # the withdrawn date no longer dates the step


def test_a_plan_that_cannot_follow_is_reported_and_the_import_still_completes(engine, world):
    _, d, tmp = world

    def broken(*a):
        raise RuntimeError("cannot recompile")

    d.on_fact_change = broken
    res = import_programme_date(d, tmp, "a.xlsx", "2027-08-15")
    assert len(res.hook_errors) == 2 and "cannot recompile" in res.hook_errors[0]
    from app.os.knowledge.sheets.importlog import ImportLog

    rec = ImportLog(engine, "pai").get(res.import_id)
    assert rec.status == "done" and "2 plan revisions failed" in rec.error  # kept in the log, not hidden
    assert d.knowledge.programme_facts(["p1"], ["merit_list_date"], 2027, intake_term="winter")  # the fact is stored


def test_only_iso_dates_are_kept_in_the_shape_the_compiler_reads(engine, world):
    _, d, tmp = world
    institutions, programmes = programme_rows()
    odd = fact(8, "p1", field_="pass_date", value="Jun 13, 2027", intake="Winter 2027")
    path = workbook(tmp, institutions, [merit_fact("2027-08-15"), odd], programmes)
    run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    got = d.knowledge.programme_facts(["p1"], ["merit_list_date", "pass_date"], 2027, intake_term="winter")
    assert got[("p1", "merit_list_date")].value == {"value": "2027-08-15", "unit": "date", "date": "2027-08-15"}
    assert got[("p1", "pass_date")].value == {"value": "Jun 13, 2027", "unit": "date"}  # never guessed
