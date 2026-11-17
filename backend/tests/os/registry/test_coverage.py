"""P2-T2: the coverage level of an institution, computed from its facts for the coming intake (P2 spec §4.1; R-34)."""

from dataclasses import replace

import pytest

from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.store import SqlKnowledge
from app.os.registry.coverage import coverage_map, summarise

from .helpers import AT, child, inst, olist, store, put

pytestmark = pytest.mark.req("R-34")
URL = "https://admissions.alpha.test/notice"


def fact(status="confirmed", year=2027, **kw) -> Fact:
    quote = "the quote" if status in ("confirmed", "verified") else ""
    url = URL if status in ("confirmed", "verified") else ""
    return Fact({"v": 1}, quote, url, AT, year, status, **kw)


@pytest.fixture
def world(engine, clean):
    s = store(engine)
    s.record(olist(rows=3), cause="import")
    for slug in ("one", "two", "tre"):
        s.record(inst(slug), cause="import")
    return s, SqlKnowledge(engine, "pai")


def levels(engine, **kw) -> dict[str, str]:
    return {k: v.level for k, v in coverage_map(engine, "pai", 2027, **kw).items()}


def test_nothing_researched_is_listed(engine, world):
    assert levels(engine) == {"inst:one": "listed", "inst:two": "listed", "inst:tre": "listed"}


def test_one_fact_for_the_intake_is_researched(engine, world):
    _, k = world
    put(k, "registry", "inst:one", "programme_detail", fact("unconfirmed"))
    put(k, "registry", "inst:two", "deadline_close", fact(year=2026, status="verified"))  # another intake
    assert levels(engine) == {"inst:one": "researched", "inst:two": "listed", "inst:tre": "listed"}


def test_verified_needs_every_high_stakes_fact_verified(engine, world):
    _, k = world
    put(k, "registry", "inst:one", "deadline_close", fact("verified"))
    put(k, "registry", "inst:one", "detail", fact("unconfirmed", fact_class="programme_detail"))  # not high-stakes: may stay unconfirmed
    assert levels(engine)["inst:one"] == "verified"
    put(k, "registry", "inst:one", "fee_x_unknown_field", fact("confirmed"))  # unclassified: high-stakes (fail safe)
    c = coverage_map(engine, "pai", 2027)["inst:one"]
    assert c.level == "researched"
    assert (c.facts, c.high_stakes, c.high_stakes_verified) == (3, 2, 1)


def test_only_non_high_stakes_facts_never_make_verified(engine, world):
    _, k = world
    put(k, "registry", "inst:one", "detail", fact("verified", fact_class="programme_detail"))
    assert levels(engine)["inst:one"] == "researched"


def test_a_stale_high_stakes_fact_drops_it_back(engine, world):
    _, k = world
    fid = put(k, "registry", "inst:one", "deadline_close", fact("verified"))
    assert levels(engine)["inst:one"] == "verified"
    k.set_status(fid, "stale", cause="monitor")
    assert levels(engine)["inst:one"] == "researched"


def test_intake_term_filter(engine, world):
    _, k = world
    put(k, "registry", "inst:one", "deadline_close", fact("verified", intake_term="autumn"))
    assert levels(engine, intake_term="autumn")["inst:one"] == "verified"
    assert levels(engine, intake_term="spring")["inst:one"] == "listed"
    assert levels(engine)["inst:one"] == "verified"  # no term given: every term


def test_programme_and_campus_facts_count_for_the_institution(engine, world):
    s, k = world
    s.record(child("campus", "campus", "north", "inst:one", list_ids=("list:alpha-list",), region="punjab"),
             cause="import")
    ProgrammeStore(engine, "pai").upsert(Programme(ref="p1", route_key="r", university="One", name="Sci", aliases=(),
                                                   start_urls=(), official_domains=()))
    s.link_programme("p1", institution_id="inst:one", campus_id="campus:north", cause="import")
    put(k, "programme", "p1", "deadline_close", fact("verified"))
    assert levels(engine)["inst:one"] == "verified"
    put(k, "registry", "campus:north", "fee_unknown", fact("confirmed"))
    assert levels(engine)["inst:one"] == "researched"
    assert levels(engine)["inst:two"] == "listed"


def shared_world(s):
    s.record(child("admission_body", "body", "central", None, region="national"), cause="import")
    s.record(child("admission_system", "sys", "central-merit", "body:central"), cause="import")
    s.record(child("entry_test", "test", "alpha-entry", "body:central"), cause="import")
    s.record(child("seat_category", "cat", "open", "sys:central-merit"), cause="import")
    s.link("sys:central-merit", "admits", "inst:one", cause="import")
    s.link("sys:central-merit", "uses_test", "test:alpha-entry", cause="import")


def test_an_admitting_system_and_its_tests_count_as_researched(engine, world):
    """P2 review I-2: shared facts (system, tests, categories, calendars) count toward `researched` only."""
    s, k = world
    shared_world(s)
    put(k, "registry", "sys:central-merit", "merit_formula", fact("verified"))
    put(k, "registry", "test:alpha-entry", "test_date", fact("verified"))
    assert levels(engine) == {"inst:one": "researched", "inst:two": "listed", "inst:tre": "listed"}
    c = coverage_map(engine, "pai", 2027)["inst:one"]
    assert (c.facts, c.high_stakes, c.high_stakes_verified, c.shared_facts) == (2, 0, 0, 2)
    put(k, "registry", "inst:one", "deadline_close", fact("verified"))  # one of its own high-stakes facts
    assert levels(engine)["inst:one"] == "verified"
    put(k, "registry", "cat:open", "seat_quota", fact("confirmed"))  # a shared high-stakes fact does not gate it
    assert levels(engine)["inst:one"] == "verified"
    put(k, "registry", "body:central", "deadline_close", fact("unconfirmed"))  # the body itself is not counted
    assert levels(engine)["inst:two"] == "listed"


def test_shared_verified_facts_alone_never_make_an_institution_verified(engine, world):
    s, k = world
    shared_world(s)
    for ref, field in (("sys:central-merit", "merit_formula"), ("test:alpha-entry", "test_date"),
                       ("cat:open", "seat_quota")):
        put(k, "registry", ref, field, fact("verified"))
    assert levels(engine)["inst:one"] == "researched"
    put(k, "registry", "inst:one", "deadline_close", fact("confirmed"))  # own, not verified yet
    assert levels(engine)["inst:one"] == "researched"


def test_a_bodys_row_about_a_programme_or_campus_is_not_research_of_it(engine, world):
    """P2 review I-1: only general rows (owner_ref '') count for the institution's own programmes and campuses."""
    s, k = world
    s.record(child("campus", "campus", "north", "inst:one", list_ids=("list:alpha-list",), region="punjab"),
             cause="import")
    ProgrammeStore(engine, "pai").upsert(Programme(ref="p1", route_key="r", university="One", name="Sci", aliases=(),
                                                   start_urls=(), official_domains=()))
    s.link_programme("p1", institution_id="inst:one", cause="import")
    put(k, "programme", "p1", "pass_mark", fact("verified", owner_ref="body:central"))
    put(k, "registry", "campus:north", "fee_x", fact("verified", owner_ref="body:central"))
    assert levels(engine)["inst:one"] == "listed"
    put(k, "programme", "p1", "deadline_close", fact("verified"))
    assert levels(engine)["inst:one"] == "verified"
    c = coverage_map(engine, "pai", 2027)["inst:one"]
    assert (c.facts, c.high_stakes) == (1, 1)


def test_not_readable_stays_listed(engine, world):
    s, k = world
    s.record(replace(inst("one"), attrs={"not_readable": True}), cause="review")
    put(k, "registry", "inst:one", "deadline_close", fact("verified"))
    c = coverage_map(engine, "pai", 2027)["inst:one"]
    assert c.level == "listed" and c.not_readable


def test_region_filter_and_closed_institutions(engine, world):
    s, _ = world
    s.record(inst("far", region="sindh"), cause="import")
    s.record(replace(inst("tre"), status="closed"), cause="review")
    assert sorted(levels(engine)) == ["inst:far", "inst:one", "inst:two"]
    assert sorted(levels(engine, region="sindh")) == ["inst:far"]
    assert summarise(coverage_map(engine, "pai", 2027)) == {"listed": 3, "researched": 0, "verified": 0}
