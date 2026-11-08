"""P2-T9 review fixes: the floor by class, facts held by admission systems and bodies, gate enforcement, dates, suspect
domains, the per-reviewer rate (R-35, R-66). Fictional bodies on `.test` sites."""

import re
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import insert

from app.os import models
from app.os.coverage import gate, report
from app.os.intakes import IntakeError, IntakeStore
from app.os.registry.coverage import coverage_map
from tests.os.registry.helpers import child, olist, put
from tests.os.test_p2_coverage_report import (  # noqa: F401
    FLOOR,
    NOW,
    fact,
    readings,
    verify_floor,
    world,
)

pytestmark = pytest.mark.req("R-35")
APP = Path(__file__).resolve().parents[2] / "app" / "os"


def test_the_floor_is_chosen_by_class_not_by_field_name(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    assert readings(engine, intake)[1]["b"].green
    put(k, "programme", "p-one", "closing_date_note", fact("confirmed", fact_class="deadline"))  # a deadline, by class
    items = readings(engine, intake)[1]["b"].items
    assert [(i.code, i.subject) for i in items] == [("not_verified", "inst:one p-one closing_date_note")]
    put(k, "programme", "p-one", "closing_date_note", fact(fact_class="deadline"))
    assert readings(engine, intake)[1]["b"].green


def test_a_field_of_a_floor_class_without_the_field_name_listed_is_still_asked(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    put(k, "programme", "p-one", "entry_rule", fact("unconfirmed", fact_class="eligibility_threshold"))
    assert [i.subject for i in readings(engine, intake)[1]["b"].items] == ["inst:one p-one entry_rule"]


def test_the_formula_held_on_an_admission_system_counts_without_a_copy(engine, world):  # noqa: F811
    """Floor reading vs level: the floor asks whether the student-facing facts are verified wherever their owner keeps
    them; the institution's own coverage level still needs its OWN high-stakes facts."""
    s, k, intake = world
    s.record(child("admission_body", "body", "central", None, region="national"), cause="import")
    s.record(child("admission_system", "sys", "central-merit", "body:central"), cause="import")
    s.link("sys:central-merit", "admits", "inst:one", cause="import")
    for f in ("deadline_close", "grade_requirement"):
        put(k, "programme", "p-one", f, fact())
    assert {i.subject for i in readings(engine, intake)[1]["b"].items} == {"inst:one p-one merit_formula"}
    put(k, "registry", "sys:central-merit", "merit_formula", fact())
    assert readings(engine, intake)[1]["b"].green
    # a formula on a system that does NOT admit the institution does not count
    s.record(child("admission_system", "sys", "other", "body:central"), cause="import")
    put(k, "registry", "sys:other", "merit_formula", fact())
    s.link("sys:central-merit", "admits", "inst:two", cause="import")
    # the level reads own facts only: inst:one has two own high-stakes facts, both verified, so it is verified, and the
    # shared formula neither makes nor breaks it
    assert coverage_map(engine, "pai", 2027, intake_term="fall")["inst:one"].level == "verified"


def test_everything_on_the_system_is_a_shared_floor_but_not_a_level(engine, world):  # noqa: F811
    s, k, intake = world
    s.record(child("admission_system", "sys", "central-merit", None, region="national"), cause="import")
    s.link("sys:central-merit", "admits", "inst:one", cause="import")
    for f in FLOOR:
        put(k, "registry", "sys:central-merit", f, fact())
    assert readings(engine, intake)[1]["b"].green
    assert coverage_map(engine, "pai", 2027, intake_term="fall")["inst:one"].level == "researched"  # not own facts


def test_a_row_an_owning_body_holds_about_the_programme_counts(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    for f in FLOOR:
        put(k, "programme", "p-one", f, replace(fact(), owner_ref="body:central"))
    assert readings(engine, intake)[1]["b"].green


def test_only_the_gate_makes_an_intake_current():
    """R-66 invariant: nothing in app/os but the gate moves an intake to current."""
    callers = {}
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("_gate_set_current", "_gate_lock"):
            if re.search(rf"\.{name}\(", text):
                callers.setdefault(name, set()).add(path.relative_to(APP).as_posix())
    assert callers == {"_gate_set_current": {"coverage/gate.py"}, "_gate_lock": {"coverage/gate.py"}}
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r'set_state\([^)]*"current"', text), path
        if path.relative_to(APP).as_posix() not in ("intakes/store.py", "models.py"):
            assert not re.search(r'state\s*=\s*"current"', text) or "coverage/" in path.as_posix(), path


def test_pass_gate_takes_the_lock_and_only_an_open_intake_passes(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    assert gate.pass_gate(engine, "pai", intake.id, NOW).state == "current"
    with pytest.raises(IntakeError, match="not open"):
        gate.pass_gate(engine, "pai", intake.id, NOW)
    with pytest.raises(IntakeError, match="gate"):
        IntakeStore(engine, "pai").set_state(intake.id, "current")


def test_a_current_intake_whose_gate_turned_red_is_flagged_not_reverted(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    gate.pass_gate(engine, "pai", intake.id, NOW)
    rep, r = readings(engine, intake)
    assert rep.green and r["e"].green
    put(k, "programme", "p-one", "merit_formula", fact("confirmed", value={"v": 2}))  # a changed value drops it
    rep, r = readings(engine, intake)
    assert not rep.green and [i.code for i in r["e"].items] == ["gate_turned_red"]
    assert IntakeStore(engine, "pai").by_id(intake.id).state == "current"  # never reverted by itself


def test_an_open_intake_never_has_reading_e_red(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    assert readings(engine, intake)[1]["e"].green


def test_a_list_without_a_date_is_red_and_several_complete_lists_are_fine(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    s.record(olist("undated", rows=2), cause="import")
    a = readings(engine, intake)[1]["a"]
    assert [(i.code, i.subject) for i in a.items] == [("no_date", "list:undated"), ("list_incomplete", "list:undated")]
    s.record(olist("undated", rows=2, date="2026-09-01"), cause="import")
    s.record(replace(olist("third", rows=0, date="2026-09-02"), entity_id="list:third"), cause="import")
    codes = [i.code for i in readings(engine, intake)[1]["a"].items]
    assert "no_date" not in codes


def test_a_suspect_domain_fails_reading_c(engine, world):  # noqa: F811
    s, k, intake = world  # noqa: RUF059
    put(k, "programme", "p-two", "deadline_close", fact("confirmed"))
    assert readings(engine, intake)[1]["c"].green
    with engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(tenant_id="pai", domain="alpha.test", region="punjab",
                                                          family="undergrad", state="suspect"))
    c = readings(engine, intake)[1]["c"]
    assert [(i.code, i.subject) for i in c.items] == [("suspect_domain", "inst:two p-two deadline_close")]


def test_the_rate_is_per_reviewer_day(engine, world):  # noqa: F811
    from sqlalchemy import text

    from app.os.coverage import workload

    s, k, intake = world  # noqa: RUF059
    for n, who in enumerate(("r1", "r1", "r2", "r2", "r2", "r2")):
        fid = k.upsert("programme", f"p-{n}", "deadline_close", replace(fact("confirmed"), intake_term="fall"))
        k.set_status(fid, "verified", cause="review", actor=who)
    with engine.begin() as conn:
        conn.execute(text("UPDATE os.os_fact_revisions SET at = :at WHERE cause = 'review'"), {"at": NOW})
    assert workload.measure(engine, "pai", NOW) == (6, 2, 2)  # 6 rows, 2 reviewer-days, 2 reviewers
    assert workload.measured_rows_per_reviewer_day(engine, "pai", NOW) == pytest.approx(3.0)
    w = report.build(engine, "pai", intake.id, NOW).workload
    assert (w.reviewers_active, w.rows_per_reviewer_day, w.work_hours_per_day) == (2, 3.0, 6.0)
    assert w.rows_per_hour == pytest.approx(0.5) and w.reviewer_hours_left == pytest.approx(w.not_verified / 0.5, abs=0.1)
    assert w.team_days_left == pytest.approx(w.not_verified / (3.0 * 2), abs=0.1)
