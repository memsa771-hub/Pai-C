"""P2-T10: the ProgrammeFacts, MeritCheck and programme_list.v2 ports on PlanQuery (P2-D27, §4.10; R-23, R-26, R-31,
R-48, row 6.25). Fictional programmes (the fake Ireland route) and `.test` sources. Verified facts only through
set_status(..., cause="review")."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import insert

from app.os import models, ports
from app.os.api.services import make_services
from app.os.contracts.programme_facts import ProgrammeFactsV1
from app.os.contracts.programme_list_v2 import ProgrammeListV2
from app.os.contracts.route_contract import IntakeRef
from app.os.knowledge import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import load_playbook_dir
from app.os.ports import plan_query
from app.os.settings import load_settings
from tests.os.test_compiler import FAKE
from tests.os.test_p2_merit_check import FORMULA, FULL, P1V, P2V

pytestmark = pytest.mark.req("R-48")
AT = datetime(2026, 11, 1, tzinfo=UTC)
URL = "https://admissions.alpha.test/n"
INTAKE = IntakeRef(term="winter", year=2027)
TERM = "winter"
HOST = {}


@pytest.fixture
def world(engine, clean, os_db):
    s = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine, playbooks=load_playbook_dir(FAKE),
                      today=lambda: date(2027, 1, 20))
    store = ProgrammeStore(engine, "pai")
    for ref in ("ie-1", "ie-2", "ie-3"):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="Alpha University", name=ref, aliases=(),
                               start_urls=(f"https://{ref}.alpha.test/",), official_domains=("alpha.test",)))
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    HOST.clear()
    ports.configure(s, student_facts=lambda ref: HOST.get(ref))
    yield s
    ports.configure(None)


def put(s, ref, field, value, year=2027, status="confirmed", term=TERM, verified=False, **kw) -> None:
    quote, url = ("the quote", URL) if status != "unconfirmed" else ("", "")
    fid = s.knowledge.upsert("programme", ref, field, Fact(value, quote, url, AT, year, status, intake_term=term, **kw))
    if verified:
        s.knowledge.set_status(fid, "verified", cause="review", actor="checker-test")


def vault(student="stu-1", **marks) -> dict:
    return {"schema": "pai.student_facts.v1", "student_ref": student, "vault_version": 1, "built_at": AT.isoformat(),
            "eligible_levels": None,
            "facts": [{"key": k, "value": v, "evidence": e, "vault_version": 1} for k, (v, e) in marks.items()]}


def entry(got, field):
    return next(f for f in got.facts if f.field == field)


def test_programme_facts_levels_sources_and_labels(world):
    put(world, "ie-1", "deadline_close", {"date": "2027-07-15"}, verified=True)
    put(world, "ie-1", "semester_start", {"date": "2027-09-01"})  # high-stakes, only confirmed
    put(world, "ie-1", "language_of_instruction", "english")  # not high-stakes: confirmed is enough
    put(world, "ie-1", "fee_note", "x", status="unconfirmed")
    put(world, "ie-1", "grade_requirement", {"min": 50}, year=2026, term=TERM, verified=True)  # last year's
    got = plan_query.programme_facts("ie-1", INTAKE)
    assert isinstance(got, ProgrammeFactsV1) and got.route_key == "ireland_master"
    dl = entry(got, "deadline_close")
    assert (dl.level, dl.value, dl.high_stakes, dl.other_intake) == ("verified", {"date": "2027-07-15"}, True, False)
    assert dl.source.url == URL and dl.source.quote == "the quote" and dl.fact_intake == INTAKE
    ss = entry(got, "semester_start")
    assert (ss.level, ss.value) == ("not_confirmed", None) and ss.source.url == URL  # the link, not the value
    lang = entry(got, "language_of_instruction")
    assert (lang.level, lang.value, lang.high_stakes) == ("confirmed", "english", False)
    unc = entry(got, "fee_note")
    assert (unc.level, unc.value, unc.source) == ("not_confirmed", None, None)
    old = entry(got, "grade_requirement")  # R-26: another year's fact says so
    assert old.other_intake and old.fact_intake.year == 2026 and old.value == {"min": 50}


def test_programme_facts_lists_the_routes_fields_as_missing(world):
    got = plan_query.programme_facts("ie-2", INTAKE)
    assert {f.field for f in got.facts} >= {"deadline_close"}
    assert {f.level for f in got.facts} == {"missing"} and all(f.value is None for f in got.facts)


def test_programme_facts_unknown_programme(world):
    assert plan_query.programme_facts("nope", INTAKE) is None


def test_row_6_10_a_changed_fact_is_the_live_fact(world):
    put(world, "ie-1", "deadline_close", {"date": "2027-07-15"}, verified=True)
    put(world, "ie-1", "deadline_close", {"date": "2027-07-22"})  # the page changed: a write drops it to unconfirmed
    dl = entry(plan_query.programme_facts("ie-1", INTAKE), "deadline_close")
    assert dl.level == "not_confirmed" and dl.value is None


def test_merit_check_port_reads_the_vault_and_the_verified_formula(world):
    put(world, "ie-1", "merit_formula", FORMULA, verified=True)
    HOST["stu-1"] = vault(**FULL)
    got = plan_query.merit_check("stu-1", "ie-1", INTAKE)
    assert got.status == "computed" and got.aggregate is not None
    HOST["stu-2"] = vault("stu-2", **{P1V: (900, "shown")})
    part = plan_query.merit_check("stu-2", "ie-1", INTAKE)
    assert part.status == "missing" and {p.name: p.status for p in part.parts}["part_two"] == "missing"
    assert P2V in {m.key for m in part.marks_used}


def test_row_6_25_merit_answer_comes_only_from_merit_check(world):
    """The unconfirmed formula is not used: the answer is "not confirmed" and no number leaves."""
    put(world, "ie-1", "merit_formula", FORMULA)  # confirmed, not verified
    HOST["stu-1"] = vault(**FULL)
    got = plan_query.merit_check("stu-1", "ie-1", INTAKE)
    assert got.status == "not_confirmed" and got.aggregate is None and got.formula is None
    mf = entry(plan_query.programme_facts("ie-1", INTAKE), "merit_formula")
    assert (mf.level, mf.value) == ("not_confirmed", None)  # ProgrammeFacts agrees with MeritCheck


def test_programme_list_v2_coverage_levels(world):
    put(world, "ie-1", "deadline_close", {"date": "2027-07-15"}, verified=True)
    put(world, "ie-2", "deadline_close", {"date": "2027-07-15"})
    got = plan_query.programme_list_v2("ireland_master", INTAKE)
    assert isinstance(got, ProgrammeListV2)
    by = {p.programme_ref: p for p in got.programmes}
    assert by["ie-1"].coverage_level == "verified" and not by["ie-1"].not_run_yet
    assert by["ie-2"].coverage_level == "researched" and not by["ie-2"].not_run_yet
    assert by["ie-3"].coverage_level == "listed" and by["ie-3"].not_run_yet
    assert all(p.region is None for p in got.programmes)  # the registry's region column is T2's
    v1 = plan_query.programme_list("ireland_master", INTAKE)  # v1 stays as it was
    assert {p.programme_ref: p.facts_confirmed for p in v1.programmes} == {
        p.programme_ref: p.facts_confirmed for p in got.programmes}
    assert plan_query.programme_list_v2("no_route", INTAKE).programmes == []
