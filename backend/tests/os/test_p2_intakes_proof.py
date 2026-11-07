"""P2-T8 proof (spec §4.8; R-26, R-61, R-62, R-63, R-64, row 6.10): a scripted rollover from a fake 2026 intake to 2027.
Values stay labelled 2026 until the 2027 ones arrive, then the plan revises on its own. A student's next-intake plan asks
nothing again that is already known. Fictional route and `.test` sites; today is fixed."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.os import models
from app.os.compiler import compile_plan
from app.os.contracts.route_contract import RouteContract
from app.os.intakes import IntakeStore
from app.os.intakes.rollover import rollover, slot_report
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.requests.state import StudentState
from app.os.service import PlanService
from app.os.settings import load_settings
from app.os.workers import supply_fact
from tests.os.test_compile_needs import INTER2

pytestmark = pytest.mark.req("R-61")
T = models.tasks
TODAY = date(2026, 11, 20)
CHECKED = datetime(2026, 11, 1, tzinfo=UTC)
GATE = datetime(2026, 9, 1, tzinfo=UTC)
URL = "https://admissions.alpha.test/notice"


def contract(year, ref="stu-1", **over) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"ext-{ref}-{year}", "student_ref": ref,
        "origin_country": "PK", "destination_country": "IE", "level": "master",
        "target_intake": {"term": "winter", "year": year},
        "programmes": [{"programme_ref": "p1", "rank": 1}], **over})


def f(year, date_, status="confirmed") -> Fact:
    return Fact({"date": date_}, "Applications close" if status == "confirmed" else "", URL if status == "confirmed" else "",
                CHECKED, year, status, intake_term="winter")


@pytest.fixture
def world(engine, clean):
    from tests.os.test_compiler import IE

    kb = SqlKnowledge(engine, "pai")
    kernel = Kernel(engine, "pai")
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), kernel, kb, {(IE.key, IE.version): IE},
                      today=lambda: TODAY)
    kb.upsert("programme", "p1", "deadline_close", f(2026, "2026-12-15"))
    s = IntakeStore(engine, "pai")
    i = s.create("r_one", "masters", "winter", 2026, state="open")
    s.set_state(i.id, "current", gate_passed_at=GATE)
    return svc, kb, kernel, s


def tasks_of(engine, plan_id):
    with engine.connect() as conn:
        return {r.instance_key: r for r in conn.execute(select(T).where(T.c.plan_id == plan_id)).all()}


def test_rollover_proof_2026_to_2027(world, engine):
    svc, kb, kernel, s = world
    # before any 2027 intake is registered the read is strict, as today
    strict = svc.start_plan(contract(2027, "early")).plan_id
    assert tasks_of(engine, strict)["apply@p1"].blocked_reason == "fact_missing:deadline_close"

    res = rollover(engine, "pai", region="r_one", family="masters", term="winter", year=2027)
    assert res.slots_added == 1 and s.fallback_applies("winter", 2027) and s.plannable("winter", 2027)

    plan_id = svc.start_plan(contract(2027)).plan_id  # R-63: a student plans for the open intake now
    apply = tasks_of(engine, plan_id)["apply@p1"]
    assert apply.provisional and apply.blocked_reason is None
    assert [c["intake_year"] for c in apply.citations if "intake_year" in c] == [2026]  # labelled, never silent
    assert tasks_of(engine, plan_id)["confirm_fact@p1:deadline_close"].state != "done"
    assert apply.fact_refs == [["programme", "p1", "deadline_close"]]  # no year: the new fact reaches it
    assert kb.programme_facts(["p1"], ["deadline_close"], 2027) == {}  # nothing copied into 2027

    revisions_before = _revisions(engine, plan_id)
    supply_fact(svc, kb, kernel, scope="programme", ref="p1", field="deadline_close", intake_year=2027,
                value={"date": "2027-01-15"}, quote="Applications close 15 January 2027", url=URL, status="confirmed")
    after = tasks_of(engine, plan_id)
    assert _revisions(engine, plan_id) == revisions_before + 1  # the plan revised on its own (row 6.10)
    assert not after["apply@p1"].provisional
    assert not [c for c in after["apply@p1"].citations if "intake_year" in c]
    gone = after.get("confirm_fact@p1:deadline_close")
    assert gone is None or gone.state in ("done", "cancelled", "skipped")  # nothing is left waiting for it
    # 2026 stays, with its year; the slot is filled
    assert kb.programme_facts(["p1"], ["deadline_close"], 2026)[("p1", "deadline_close")].value == {"date": "2026-12-15"}
    assert [r.state for r in slot_report(engine, "pai", res.intake.id)] == ["confirmed"]

    # a 2026 plan was never touched by the 2027 fact
    old = svc.start_plan(contract(2026, "old")).plan_id
    assert not tasks_of(engine, old)["apply@p1"].provisional


def test_gate_closes_the_fallback(world, engine):
    svc, _kb, _kernel, s = world
    res = rollover(engine, "pai", region="r_one", family="masters", term="winter", year=2027)
    s.set_state(res.intake.id, "current", gate_passed_at=datetime(2026, 11, 19, tzinfo=UTC))
    assert not s.fallback_applies("winter", 2027)
    plan_id = svc.start_plan(contract(2027)).plan_id  # the strict read again: no fact, so blocked, nothing borrowed
    assert tasks_of(engine, plan_id)["apply@p1"].blocked_reason == "fact_missing:deadline_close"


def _revisions(engine, plan_id) -> int:
    with engine.connect() as conn:
        return conn.execute(select(models.plan_revisions.c.id).where(
            models.plan_revisions.c.plan_id == plan_id)).all().__len__()


@pytest.mark.req("R-64")
def test_next_intake_plan_asks_nothing_that_is_already_known():
    """The Vault and documents are the student's, not the plan's: a plan for the next intake reads the same state, so a
    fact the student already gave is met, and only what was missing is asked, again the same way."""
    known = StudentState(facts={"education.matric.marks_obtained": "stated"})

    def build(year):
        c = contract(year).model_copy(update={"origin_country": "PK", "destination_country": "PK", "level": "bachelor"})
        merit = {("p1", "merit_list_date"): Fact({"date": f"{year}-08-15"}, "q", URL, CHECKED, year, "confirmed")}
        return compile_plan(c, INTER2, {}, merit, date(year - 1, 11, 20), student=known)

    this_year, next_year = build(2027), build(2028)
    given = "provide@fact:education.matric.marks_obtained:stated"
    asked = {y: {t.instance_key for t in d.tasks if t.instance_key.startswith("provide@")}
             for y, d in ((2027, this_year), (2028, next_year))}
    assert asked[2027] == asked[2028] and given not in asked[2028]
    assert given in next_year.answered
    assert asked[2028]  # the fact the student has not given is still asked, once


def test_builder_refuses_an_intake_that_is_not_open(world, engine):
    from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice
    from app.os.knowledge.programmes import Programme, ProgrammeStore
    from app.os.routes import builder

    svc, _kb, _kernel, s = world
    ProgrammeStore(engine, "pai").upsert(Programme("p1", "ireland_master", "Alpha University", "Programme", (), (), ()))
    choice = [ProgrammeChoice(programme_ref="p1", rank=1)]
    s.create("r_one", "masters", "winter", 2028)  # registered, still planned
    with pytest.raises(builder.NotAllowed, match="not open"):
        builder.start(svc, "stu-9", "ireland_master", IntakeRef(term="winter", year=2028), choice)
    rollover(engine, "pai", region="r_one", family="masters", term="winter", year=2028)  # now open
    assert builder.start(svc, "stu-9", "ireland_master", IntakeRef(term="winter", year=2028), choice).created
