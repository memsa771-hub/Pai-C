"""P2-T9: the coverage report and the R-35 (a)-(d) reading per intake (R-34, R-35, R-66). Fictional bodies, `.test` sites."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.os.coverage import gate, report
from app.os.intakes import IntakeStore
from app.os.intakes.rollover import rollover
from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.store import SqlKnowledge
from tests.os.registry.helpers import AT, inst, olist, put, store

pytestmark = pytest.mark.req("R-35")
NOW = datetime(2027, 1, 10, tzinfo=UTC)
URL = "https://admissions.alpha.test/notice"
FLOOR = ("deadline_close", "merit_formula", "grade_requirement")


def fact(status="verified", term="fall", year=2027, value=None, **kw) -> Fact:
    sourced = status != "unconfirmed"
    return Fact({"v": 1} if value is None else value, "the quote" if sourced else "", URL if sourced else "", AT, year,
                status, intake_term=term, **kw)


def programme(engine, s, ref, institution, family="undergrad"):
    ProgrammeStore(engine, "pai").upsert(Programme(ref=ref, route_key="r", university="U", name=ref, aliases=(),
                                                   start_urls=(), official_domains=()))
    s.link_programme(ref, institution_id=institution, family=family, region="punjab", cause="import")


@pytest.fixture
def world(engine, clean):
    s = store(engine)
    s.record(olist(rows=2), cause="import")
    s.record(inst("one", attrs={"first_live": ["fall:2027"]}), cause="import")
    s.record(inst("two"), cause="import")
    programme(engine, s, "p-one", "inst:one")
    programme(engine, s, "p-two", "inst:two")
    ins = IntakeStore(engine, "pai")
    intake = ins.create("punjab", "undergrad", "fall", 2027, state="open")
    return s, SqlKnowledge(engine, "pai"), intake


def verify_floor(k, ref="p-one"):
    for f in FLOOR:
        put(k, "programme", ref, f, fact())


def readings(engine, intake):
    rep = report.build(engine, "pai", intake.id, NOW)
    return rep, {r.gate: r for r in rep.readings}


def test_rows_count_levels_lists_and_high_stakes(engine, world):
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    put(k, "programme", "p-two", "deadline_close", fact("confirmed"))  # high-stakes, not verified
    rep, _ = readings(engine, intake)
    (row,) = rep.rows
    assert (row.institution_type, row.institutions) == ("university", 2)
    assert (row.verified, row.researched, row.listed) == (1, 1, 0)
    assert row.lists == [{"list_id": "list:alpha-list", "name": "Alpha recognised institutions", "region": "national",
                          "published": 2, "loaded": 2, "count_confirmed": True}]
    assert row.hs_verified == 3 and row.hs_not_confirmed == 1 and row.hs_missing == 2  # p-two: 1 held, 2 floor missing
    assert rep.workload.not_verified == 3 and rep.workload.hours_left is None  # nobody has reviewed yet


def test_gate_a_the_denominator(engine, world):
    s, k, intake = world  # noqa: RUF059
    assert readings(engine, intake)[1]["a"].green
    s.record(olist(rows=3), cause="import")  # the list now says 3, 2 are loaded
    a = readings(engine, intake)[1]["a"]
    assert [(i.code, i.subject) for i in a.items] == [("list_incomplete", "list:alpha-list")] and not a.green
    s.record(olist(rows=2, count_confirmed=False), cause="import")
    assert readings(engine, intake)[1]["a"].items[0].code == "count_unconfirmed"
    s.record(replace(olist(rows=2), institution_type="college"), cause="import")  # the list is for another type
    assert readings(engine, intake)[1]["a"].items[0].code == "no_list"


def test_gate_b_the_verified_floor_of_first_live_institutions_only(engine, world):
    s, k, intake = world  # noqa: RUF059
    _, r = readings(engine, intake)
    assert not r["b"].green and r["b"].checked == 1  # inst:two is not first-live: not asked
    assert {i.code for i in r["b"].items} == {"missing"} and len(r["b"].items) == 3
    put(k, "programme", "p-one", "deadline_close", fact("confirmed"))
    put(k, "programme", "p-one", "merit_formula", fact())
    put(k, "programme", "p-one", "grade_requirement", fact())
    codes = {i.subject: i.code for i in readings(engine, intake)[1]["b"].items}
    assert codes == {"inst:one p-one deadline_close": "not_verified"}
    put(k, "programme", "p-one", "deadline_close", fact())
    assert readings(engine, intake)[1]["b"].green


def test_gate_b_is_also_met_by_a_verified_fact_of_the_institution(engine, world):
    s, k, intake = world  # noqa: RUF059
    for f in FLOOR:
        put(k, "registry", "inst:one", f, fact())
    assert readings(engine, intake)[1]["b"].green


def test_gate_b_reads_the_rollover_slots(engine, world):
    s, k, intake = world  # noqa: RUF059
    put(k, "programme", "p-one", "fee", fact(term="fall", year=2026))  # last year's high-stakes key
    verify_floor(k)
    prev = IntakeStore(engine, "pai").create("punjab", "undergrad", "fall", 2026, state="open")  # noqa: F841
    res = rollover(engine, "pai", region="punjab", family="undergrad", term="fall", year=2027)
    assert res.slots_added >= 1
    items = readings(engine, intake)[1]["b"].items
    assert [(i.code, i.subject) for i in items] == [("missing", "inst:one p-one fee")]


def test_gate_c_not_confirmed_must_carry_the_official_link(engine, world):
    s, k, intake = world  # noqa: RUF059
    put(k, "programme", "p-two", "deadline_close", fact("confirmed"))
    assert readings(engine, intake)[1]["c"].green
    put(k, "programme", "p-two", "fee", fact("unconfirmed"))  # high-stakes, no URL, no quote
    c = readings(engine, intake)[1]["c"]
    assert [(i.code, i.subject) for i in c.items] == [("no_link", "inst:two p-two fee")]


def test_gate_d_a_place_with_no_online_information_stays_listed(engine, world):
    s, k, intake = world
    s.record(inst("three", attrs={"not_readable": True}), cause="import")
    programme(engine, s, "p-three", "inst:three")
    put(k, "programme", "p-three", "deadline_close", fact())
    rep, r = readings(engine, intake)
    assert r["d"].green and r["d"].checked == 1
    assert rep.rows[0].not_readable == 1 and rep.rows[0].verified == 0  # its verified fact does not lift it


def test_other_families_and_regions_are_not_in_this_intake(engine, world):
    s, k, intake = world  # noqa: RUF059
    programme(engine, s, "p-other", "inst:two", family="postgrad")
    s.record(inst("far", region="sindh"), cause="import")
    rep, _ = readings(engine, intake)
    assert rep.rows[0].institutions == 2


def test_green_when_everything_holds_and_pass_gate_records_it(engine, world):
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    rep, r = readings(engine, intake)
    assert rep.green and all(x.green for x in r.values())
    assert rep.failing() == []
    now = gate.pass_gate(engine, "pai", intake.id, NOW)
    assert now.state == "current" and now.gate_passed_at == NOW


def test_pass_gate_refuses_while_red_and_changes_nothing(engine, world):
    s, k, intake = world  # noqa: RUF059
    with pytest.raises(gate.GateRed) as e:
        gate.pass_gate(engine, "pai", intake.id, NOW)
    assert {f["gate"] for f in e.value.failing} == {"b"} and e.value.failing[0]["code"] == "missing"
    after = IntakeStore(engine, "pai").by_id(intake.id)
    assert after.state == "open" and after.gate_passed_at is None


def test_workload_uses_the_measured_review_rate(engine, world):
    s, k, intake = world  # noqa: RUF059
    verify_floor(k)
    put(k, "programme", "p-two", "deadline_close", fact("confirmed"))
    rep = report.build(engine, "pai", intake.id, NOW)
    assert rep.workload.not_verified == 3 and rep.workload.checks_left == 6
    assert rep.workload.checks_needed == round(rep.workload.institutions * rep.workload.high_stakes_per_institution) * 2
    # three rows verified by review on one day = 3 rows over 6 work hours
    for f in FLOOR:
        fid = k.upsert("programme", "p-two", f, replace(fact("confirmed"), intake_term="fall"))
        k.set_status(fid, "verified", cause="review")
    from sqlalchemy import text

    from app.os.coverage import workload
    with engine.begin() as conn:
        conn.execute(text("UPDATE os.os_fact_revisions SET at = :at WHERE cause = 'review'"), {"at": NOW})
    assert workload.measured_rows_per_hour(engine, "pai", NOW) == pytest.approx(
        conn_count(engine) / 6)  # one worked day
    # nothing measured in the window: no rate, no hours
    assert workload.measured_rows_per_hour(engine, "pai", datetime(2028, 6, 1, tzinfo=UTC)) is None


def conn_count(engine) -> int:
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM os.os_fact_revisions WHERE cause='review' AND "
                                 "action='status' AND after->>'status'='verified'")).scalar_one()


def test_suspect_domains_and_open_review_items_are_counted(engine, world):
    from sqlalchemy import insert

    from app.os import models

    s, k, intake = world  # noqa: RUF059
    with engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(tenant_id="pai", domain="odd.alpha.test", region="punjab",
                                                          family="", state="suspect"))
        conn.execute(insert(models.source_domains).values(tenant_id="pai", domain="other.alpha.test", region="sindh",
                                                          family="", state="suspect"))
        conn.execute(insert(models.review_items).values(tenant_id="pai", kind="verify", dedupe_key="k1",
                                                        intake_year=2027, intake_term="fall"))
        conn.execute(insert(models.review_items).values(tenant_id="pai", kind="verify", dedupe_key="k2",
                                                        intake_year=2026, intake_term="fall"))
    rep = report.build(engine, "pai", intake.id, NOW)
    assert rep.suspect_domains == ["odd.alpha.test"] and rep.open_review_items == {"verify": 1}
