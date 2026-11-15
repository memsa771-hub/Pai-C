"""P3-T6 (ADR-001 D9; R-63, R-38): intakes are region- and family-aware.

A plan is plannable only when the (region, family, term, year) intake of every chosen place is open or current; the
labelled previous-year fallback (P2-D24) is read per place's own region. A place's region and family come from its
programme row. A place with no registered intake (no region, no family, or no row) keeps today's rule, so a route
with no family (Germany, the fakes) behaves as before. All regions, families and programmes here are synthetic."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, update

from app.os import models
from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice, RouteContract
from app.os.intakes import IntakeNotOpen, IntakeStore, places_of
from app.os.intakes.rollover import rollover
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import load_playbook_dir
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.intake_helpers import make_current

pytestmark = [pytest.mark.req("R-63"), pytest.mark.req("R-38")]
T = models.tasks
TODAY = date(2026, 11, 20)
CHECKED = datetime(2026, 11, 1, tzinfo=UTC)
GATE = datetime(2026, 9, 1, tzinfo=UTC)
URL = "https://admissions.alpha.test/notice"
FAM = "fam_one"
ONE, TWO = ("r_one", FAM), ("r_two", FAM)


def contract(refs, ref="stu-1", year=2027) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"ext-{ref}-{year}", "student_ref": ref,
        "origin_country": "PK", "destination_country": "IE", "level": "master",
        "target_intake": {"term": "winter", "year": year},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


def f(year, date_) -> Fact:
    return Fact({"date": date_}, "Applications close", URL, CHECKED, year, "confirmed", intake_term="winter")


def place(engine, ref, region=None, family=None):
    """A programme row with its region and family columns set directly (the registry link is T2's lane; the region
    code list is data, and these codes are synthetic)."""
    ProgrammeStore(engine, "pai").upsert(Programme(ref, "ireland_master", "Alpha University", ref, (), (), ()))
    with engine.begin() as conn:
        conn.execute(update(models.programmes).where(
            models.programmes.c.tenant_id == "pai", models.programmes.c.ref == ref).values(region=region, family=family))


@pytest.fixture
def world(engine, clean):
    from tests.os.test_compiler import IE

    kb = SqlKnowledge(engine, "pai")
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb,
                      {(IE.key, IE.version): IE}, today=lambda: TODAY)
    place(engine, "p_a", *ONE)
    place(engine, "p_b", *TWO)
    place(engine, "p_x")  # a place with no region or family: no registered intake
    return svc, kb, IntakeStore(engine, "pai")


def tasks_of(engine, plan_id):
    with engine.connect() as conn:
        return {r.instance_key: r for r in conn.execute(select(T).where(T.c.plan_id == plan_id)).all()}


def test_places_come_from_the_programme_row(world, engine):
    assert places_of(engine, "pai", ["p_a", "p_x", "nope"]) == {"p_a": ONE, "p_x": (None, None), "nope": (None, None)}
    assert places_of(engine, "pai", []) == {}


def test_two_regions_with_different_intake_states(world):
    _svc, _kb, s = world
    s.create(*ONE, "winter", 2027, state="open")
    s.create(*TWO, "winter", 2027)  # registered, still planned
    assert s.plannable("winter", 2027)  # the term-wide rule alone, as before: some region is open
    assert s.plannable("winter", 2027, [ONE])
    assert not s.plannable("winter", 2027, [TWO])
    assert not s.plannable("winter", 2027, [ONE, TWO])
    # family-aware: r_one's intake of another family is not registered, so today's rule holds for that place
    assert s.plannable("winter", 2027, [("r_one", "fam_two")])
    assert s.fallback_applies("winter", 2027, ONE) and not s.fallback_applies("winter", 2027, TWO)
    assert s.fallback_year("winter", 2027, ONE) == 2026 and s.fallback_year("winter", 2027, TWO) is None


def test_a_two_region_plan_with_one_region_closed_is_refused(world, engine):
    from app.os.routes import builder

    svc, _kb, s = world
    s.create(*ONE, "winter", 2027, state="open")
    two = s.create(*TWO, "winter", 2027, state="open")
    s.set_state(two.id, "closed")
    with pytest.raises(IntakeNotOpen):
        svc.start_plan(contract(["p_a", "p_b"]))
    choices = [ProgrammeChoice(programme_ref=r, rank=i + 1) for i, r in enumerate(["p_a", "p_b"])]
    with pytest.raises(builder.NotAllowed, match="not open"):
        builder.start(svc, "stu-2", "ireland_master", IntakeRef(term="winter", year=2027), choices)
    assert svc.start_plan(contract(["p_a"], "stu-3")).created  # the open region alone plans
    # a place with no registered intake beside the open one: today's rule for it (some region is open)
    assert svc.start_plan(contract(["p_a", "p_x"], "stu-4")).created


def test_the_fallback_is_taken_per_region(world, engine):
    svc, kb, s = world
    for ref in ("p_a", "p_b"):
        # synthetic dates still ahead of TODAY, so a borrowed one dates the step
        kb.upsert("programme", ref, "deadline_close", f(2025, "2027-01-10"))
        kb.upsert("programme", ref, "deadline_close", f(2026, "2027-01-20"))
    old = s.create(*ONE, "winter", 2025, state="open")
    make_current(engine, old.id, GATE)
    rollover(engine, "pai", region="r_one", family=FAM, term="winter", year=2027)  # open, opened from 2025
    two = s.create(*TWO, "winter", 2027, state="open")
    make_current(engine, two.id, GATE)
    # the term-wide rule sees a current region and reads nothing earlier; each place reads its own region
    assert s.fallback_year("winter", 2027) is None
    assert s.fallback_year("winter", 2027, ONE) == 2025  # the year the region's intake was opened from
    assert s.fallback_year("winter", 2027, TWO) is None
    rule, own = s.fallback_years("winter", 2027, places_of(engine, "pai", ["p_a", "p_b", "p_x"]))
    assert (rule, own) == (None, {"p_a": 2025, "p_b": None, "p_x": None})

    got = tasks_of(engine, svc.start_plan(contract(["p_a", "p_b"])).plan_id)
    a, b = got["apply@p_a"], got["apply@p_b"]
    assert a.provisional and a.blocked_reason is None
    assert [c["intake_year"] for c in a.citations if "intake_year" in c] == [2025]  # labelled with its own year
    assert b.blocked_reason == "fact_missing:deadline_close"  # its region is current: the strict read, as before
    assert not [c for c in b.citations if "intake_year" in c]


def test_no_registered_intake_keeps_todays_rule(world, engine):
    svc, kb, s = world
    unregistered = [(None, None), ("r_one", None), (None, FAM), ("r_nine", FAM)]

    def same_as_rule():
        for p in unregistered:
            assert s.plannable("winter", 2027, [p]) == s.plannable("winter", 2027)
            assert s.fallback_applies("winter", 2027, p) == s.fallback_applies("winter", 2027)
            assert s.fallback_year("winter", 2027, p) == s.fallback_year("winter", 2027)
        assert s.plannable("winter", 2027, unregistered) == s.plannable("winter", 2027)

    same_as_rule()  # nothing registered: plannable, no fallback
    assert s.plannable("winter", 2027, unregistered) and s.fallback_year("winter", 2027, (None, None)) is None
    one = s.create(*ONE, "winter", 2027)
    same_as_rule()  # planned only: not plannable
    assert not s.plannable("winter", 2027, [(None, None)])
    s.set_state(one.id, "open")
    same_as_rule()  # open: plannable, the fallback of the year before
    assert s.fallback_year("winter", 2027, (None, None)) == 2026

    kb.upsert("programme", "p_x", "deadline_close", f(2026, "2026-12-15"))
    x = tasks_of(engine, svc.start_plan(contract(["p_x"])).plan_id)["apply@p_x"]
    assert x.provisional and [c["intake_year"] for c in x.citations if "intake_year" in c] == [2026]


class Spy:
    """A Knowledge port that records each read and answers like the real one."""

    def __init__(self, real):
        self.real, self.calls = real, []

    def __getattr__(self, name):
        method = getattr(self.real, name)

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return method(*args, **kwargs)
        return call


@pytest.mark.parametrize("states", [("open",), ("open", "current"), ("planned",)])
def test_germany_reads_exactly_as_before(engine, clean, states):
    """Germany's places have no region or family, so every read is the one of before D9: a single programme read with
    the term-wide fallback rule, whatever the region intakes registered for the term."""
    books = load_playbook_dir()
    s = IntakeStore(engine, "pai")
    for i, state in enumerate(states):
        intake = s.create(f"r_{i}", FAM, "winter", 2027, state="planned" if state == "planned" else "open")
        if state == "current":
            make_current(engine, intake.id, GATE)
    refs = ["de-a.test", "de-b.test"]
    ProgrammeStore(engine, "pai").upsert(Programme("de-a.test", "germany_master", "Alpha", "A", (), (), ()))  # no region
    rule = s.fallback_year("winter", 2027)
    legacy = {"intake_term": "winter", "fallback_previous": True, "fallback_year": rule} if rule is not None else {}
    for key, version in sorted(k for k in books if k[0] == "germany_master"):
        book = books[(key, version)]
        spy = Spy(SqlKnowledge(engine, "pai"))
        svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), spy, books,
                          today=lambda: TODAY)
        c = contract(refs).model_copy(update={"destination_country": "DE"})
        svc.compile(c, book)
        reads = [(n, a, k) for n, a, k in spy.calls if n == "programme_facts"]
        assert len(reads) == 1
        assert reads[0][1][0] == refs and reads[0][2] == legacy
        assert all(k == legacy for n, _a, k in spy.calls if n in ("route_facts", "registry_facts"))
        assert s.plannable("winter", 2027, places_of(engine, "pai", refs).values()) == s.plannable("winter", 2027)
