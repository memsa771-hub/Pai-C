"""P2-T2: recording, reading and linking registry rows (P2 spec §4.1; R-32, R-33, R-60)."""

from dataclasses import replace

import pytest
from sqlalchemy import update

from app.os import models
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.registry.store import RegistryError

from .helpers import AT, child, inst, olist, seed_basic, store

pytestmark = pytest.mark.req("R-32")


def test_record_inserts_then_reports_unchanged(engine, clean):
    s = store(engine)
    first = s.record(olist(), cause="import", cause_ref="imp-1", actor="job")
    assert first.action == "insert"
    assert s.record(olist(), cause="import").action == "unchanged"
    assert s.get("list:alpha-list") == olist()
    assert s.get("list:nope") is None


def test_change_is_a_revision_and_history_is_kept(engine, clean):
    s = store(engine)
    seed_basic(s)
    s.record(replace(inst("one"), name="One Renamed University"), cause="review", cause_ref="rv-9", actor="rev-1")
    revs = s.revisions("inst:one")
    assert [r.action for r in revs] == ["insert", "change"]
    assert revs[1].before["name"] == "One Test University" and revs[1].after["name"] == "One Renamed University"
    assert (revs[1].cause, revs[1].cause_ref, revs[1].actor) == ("review", "rv-9", "rev-1")
    s.record(replace(inst("one"), name="One Renamed University", status="closed"), cause="review")
    assert s.revisions("inst:one")[-1].action == "status"
    assert not hasattr(s, "delete")  # nothing is deleted: a closed entity keeps its row (R-60)


def test_unknown_cause_is_refused(engine, clean):
    with pytest.raises(ValueError, match="cause"):
        store(engine).record(olist(), cause="guess")


def test_institution_must_name_existing_official_lists(engine, clean):
    s = store(engine)
    with pytest.raises(RegistryError, match="list:alpha-list"):
        s.record(inst("one"), cause="import")  # the list is not recorded yet
    s.record(olist(), cause="import")
    s.record(inst("one"), cause="import")
    s.record(inst("tre", lists=("list:alpha-list", "list:alpha-list")), cause="import")
    with pytest.raises(RegistryError, match="official_list"):
        s.record(inst("two", lists=("inst:one",)), cause="import")


def test_parent_and_successor_must_exist(engine, clean):
    s = store(engine)
    seed_basic(s)
    with pytest.raises(RegistryError, match="parent"):
        s.record(child("campus", "campus", "north", "inst:ghost", list_ids=("list:alpha-list",), region="punjab"),
                 cause="import")
    with pytest.raises(RegistryError, match="institution"):  # a campus belongs to an institution
        s.record(child("campus", "campus", "north", "list:alpha-list", list_ids=("list:alpha-list",),
                       region="punjab"), cause="import")
    s.record(child("campus", "campus", "north", "inst:one", list_ids=("list:alpha-list",), region="punjab"),
             cause="import")
    with pytest.raises(RegistryError, match="successor"):
        s.record(replace(inst("one"), status="merged", successor_id="inst:ghost"), cause="review")
    s.record(replace(inst("one"), status="merged", successor_id="inst:two"), cause="review")
    with pytest.raises(RegistryError, match="itself"):
        s.record(replace(inst("two"), status="renamed", successor_id="inst:two"), cause="review")


def test_list_filters(engine, clean):
    s = store(engine)
    seed_basic(s, rows=2)
    s.record(child("admission_body", "body", "central", None, region="national"), cause="import")
    assert [e.entity_id for e in s.list(kind="institution")] == ["inst:one", "inst:two"]
    assert [e.entity_id for e in s.list(kind="institution", region="sindh")] == ["inst:two"]
    assert [e.entity_id for e in s.list(q="TWO")] == ["inst:two"]
    assert [e.entity_id for e in s.list(list_id="list:alpha-list")] == ["inst:one", "inst:two"]
    assert [e.entity_id for e in s.list(kind="institution", limit=1, offset=1)] == ["inst:two"]
    s.record(replace(inst("two", region="sindh"), status="closed"), cause="review")
    assert [e.entity_id for e in s.list(kind="institution", status="closed")] == ["inst:two"]
    assert s.children("inst:one") == []


@pytest.mark.req("R-33")
def test_systems_tests_categories_and_what_they_admit(engine, clean):
    s = store(engine)
    seed_basic(s)
    s.record(child("admission_body", "body", "central", None, region="national"), cause="import")
    s.record(child("admission_system", "sys", "central-merit", "body:central"), cause="import")
    s.record(child("entry_test", "test", "alpha-entry", "body:central"), cause="import")
    s.record(child("seat_category", "cat", "open-merit", "sys:central-merit"), cause="import")
    s.record(child("calendar", "cal", "central-2027", "sys:central-merit"), cause="import")
    assert [e.entity_id for e in s.children("sys:central-merit")] == ["cat:open-merit", "cal:central-2027"]
    s.link("sys:central-merit", "uses_test", "test:alpha-entry", cause="import")
    s.link("sys:central-merit", "uses_test", "test:alpha-entry", cause="import")  # again: no second edge
    s.link("sys:central-merit", "has_category", "cat:open-merit", cause="import")
    s.link("sys:central-merit", "admits", "inst:one", cause="import")
    assert [(l.rel, l.to_id) for l in s.links_from("sys:central-merit")] == [
        ("uses_test", "test:alpha-entry"), ("has_category", "cat:open-merit"), ("admits", "inst:one")]
    assert [l.from_id for l in s.links_to("inst:one")] == ["sys:central-merit"]
    assert [l.to_id for l in s.links_from("sys:central-merit", rel="admits")] == ["inst:one"]


def test_link_rules(engine, clean):
    s = store(engine)
    seed_basic(s)
    s.record(child("admission_system", "sys", "central-merit", None), cause="import")
    s.record(child("entry_test", "test", "alpha-entry", None), cause="import")
    with pytest.raises(RegistryError, match="seat_category"):  # a test is not a seat category
        s.link("sys:central-merit", "has_category", "test:alpha-entry", cause="import")
    with pytest.raises(RegistryError, match="admission_system"):
        s.link("inst:one", "uses_test", "test:alpha-entry", cause="import")
    with pytest.raises(RegistryError, match="exist"):
        s.link("sys:central-merit", "admits", "inst:ghost", cause="import")
    with pytest.raises(RegistryError, match="exist"):
        s.link("sys:central-merit", "admits", "no-such-programme", to_kind="programme", cause="import")
    with pytest.raises(ValueError, match="rel"):
        s.link("sys:central-merit", "owns", "inst:one", cause="import")


@pytest.mark.req("R-33")
def test_programmes_link_to_institution_and_campus(engine, clean):
    s = store(engine)
    seed_basic(s)
    s.record(child("campus", "campus", "north", "inst:one", list_ids=("list:alpha-list",), region="punjab"),
             cause="import")
    ps = ProgrammeStore(engine, "pai")
    ps.upsert(Programme(ref="p1", route_key="fam_route", university="One Test University", name="Test Science",
                        aliases=(), start_urls=(), official_domains=()))
    assert ps.get("p1").institution_id is None
    s.link_programme("p1", institution_id="inst:one", campus_id="campus:north", level="bachelor", field="science",
                     family="bachelor", region="punjab", cause="import")
    p = ps.get("p1")
    assert (p.institution_id, p.campus_id, p.level, p.field, p.family, p.region) == (
        "inst:one", "campus:north", "bachelor", "science", "bachelor", "punjab")
    assert s.programmes_of("inst:one") == ["p1"] and s.programmes_of("inst:two") == []
    with pytest.raises(RegistryError, match="programme"):
        s.link_programme("ghost", institution_id="inst:one", cause="import")
    with pytest.raises(RegistryError, match="institution"):
        s.link_programme("p1", institution_id="inst:ghost", cause="import")
    with pytest.raises(RegistryError, match="campus"):  # the campus belongs to another institution
        s.link_programme("p1", institution_id="inst:two", campus_id="campus:north", cause="import")
    with pytest.raises(ValueError, match="region"):
        s.link_programme("p1", institution_id="inst:one", region="narnia", cause="import")
    # a re-seed of the programme (the old way) leaves the registry columns alone
    ps.upsert(Programme(ref="p1", route_key="fam_route", university="One Test University", name="Test Science 2",
                        aliases=(), start_urls=(), official_domains=()))
    assert ps.get("p1").institution_id == "inst:one"


def test_list_progress(engine, clean):
    s = store(engine)
    seed_basic(s, rows=3)
    p = s.list_progress("list:alpha-list")
    assert (p.published, p.loaded, p.complete, p.over, p.count_confirmed) == (3, 2, False, False, True)
    assert p.ratio == pytest.approx(2 / 3)
    s.record(inst("tre"), cause="import")
    assert s.list_progress("list:alpha-list").complete
    s.record(inst("four"), cause="import")
    p = s.list_progress("list:alpha-list")
    assert p.over and not p.complete
    s.record(olist("conflicted", rows=None, status="conflict"), cause="import")
    q = s.list_progress("list:conflicted")
    assert (q.published, q.ratio, q.complete) == (None, None, False)
    with pytest.raises(KeyError):
        s.list_progress("inst:one")
    assert [p.list_id for p in s.list_progresses()] == ["list:alpha-list", "list:conflicted"]


def test_existence_readers_ignore_a_bodys_rows(engine, clean):
    """P2-T2 owner semantics: a row a body owns about a programme is not research of the programme."""
    from tests.os.registry.helpers import put
    from app.os.knowledge.port import Fact
    from app.os.knowledge.requests import _facts_for
    from app.os.knowledge.store import SqlKnowledge

    k = SqlKnowledge(engine, "pai")
    put(k, "programme", "p1", "pass_mark", Fact(1, "", "", AT, 2027, "unconfirmed", owner_ref="body:central"))
    assert not _facts_for(engine, "pai", "p1", 2027)
    put(k, "programme", "p1", "deadline_close", Fact(1, "", "", AT, 2027, "unconfirmed"))
    assert _facts_for(engine, "pai", "p1", 2027)


# --- review fixes (P2-T2 review) -------------------------------------------------------------------------------------


def test_link_writes_a_revision_with_cause_and_snapshot(engine, clean):
    """I-3: a link is a change of the registry; it is kept with its cause, actor and before/after."""
    s = store(engine)
    seed_basic(s)
    s.record(child("admission_system", "sys", "central-merit", None), cause="import")
    s.record(child("entry_test", "test", "alpha-entry", None), cause="import")
    before = len(s.revisions("sys:central-merit"))
    s.link("sys:central-merit", "uses_test", "test:alpha-entry", cause="research", cause_ref="run-4", actor="job")
    s.link("sys:central-merit", "uses_test", "test:alpha-entry", cause="research")  # again: nothing new
    revs = s.revisions("sys:central-merit")
    assert len(revs) == before + 1
    r = revs[-1]
    assert (r.kind, r.subject, r.cause, r.cause_ref, r.actor) == ("link", "uses_test:registry:test:alpha-entry",
                                                                  "research", "run-4", "job")
    assert r.before == {"links": []} and r.after == {"links": ["uses_test:registry:test:alpha-entry"]}
    assert all(x.kind == "entity" for x in revs[:before])


def test_link_programme_writes_a_revision_and_does_not_clear_silently(engine, clean):
    s = store(engine)
    seed_basic(s)
    ps = ProgrammeStore(engine, "pai")
    ps.upsert(Programme(ref="p1", route_key="r", university="One", name="Sci", aliases=(), start_urls=(),
                        official_domains=()))
    s.link_programme("p1", institution_id="inst:one", level="bachelor", field="science", cause="import",
                     cause_ref="imp-3", actor="job")
    r = [x for x in s.revisions("inst:one") if x.kind == "programme"][-1]
    assert (r.subject, r.cause, r.cause_ref, r.actor) == ("p1", "import", "imp-3", "job")
    assert r.before["institution_id"] is None and r.after["institution_id"] == "inst:one"
    assert r.after["level"] == "bachelor"
    # a column left out stays; an explicit None is refused unless clear=True
    s.link_programme("p1", institution_id="inst:one", family="bachelor", cause="import")
    assert ps.get("p1").level == "bachelor" and ps.get("p1").family == "bachelor"
    with pytest.raises(RegistryError, match="clear"):
        s.link_programme("p1", institution_id="inst:one", level=None, cause="import")
    assert ps.get("p1").level == "bachelor"
    s.link_programme("p1", institution_id="inst:one", level=None, clear=True, cause="review")
    assert ps.get("p1").level is None and ps.get("p1").field == "science"
    # moving to another institution is a revision on both
    s.link_programme("p1", institution_id="inst:two", cause="review")
    assert [x.subject for x in s.revisions("inst:one") if x.kind == "programme"][-1] == "p1"
    assert s.revisions("inst:two")[-1].kind == "programme"
    n = len(s.revisions("inst:two"))
    s.link_programme("p1", institution_id="inst:two", cause="review")  # nothing changed: no revision
    assert len(s.revisions("inst:two")) == n


def test_causes_of_institutions_and_campuses_are_narrowed(engine, clean):
    s = store(engine)
    s.record(olist(), cause="seed")  # a list may still come from any listed cause
    for bad in ("seed", "manual", "report"):
        with pytest.raises(ValueError, match="cause"):
            s.record(inst("one"), cause=bad)
    for ok in ("import", "review", "research", "monitor", "rollover"):
        s.record(inst(f"i-{ok}"), cause=ok)
    s.record(inst("one"), cause="import")
    with pytest.raises(ValueError, match="cause"):
        s.link_programme("p1", institution_id="inst:one", cause="manual")


def test_a_list_must_be_of_the_institutions_region_or_national(engine, clean):
    s = store(engine)
    s.record(olist("south-list", region="sindh"), cause="import")
    s.record(olist(), cause="import")  # national
    with pytest.raises(RegistryError, match="region"):
        s.record(inst("one", region="punjab", lists=("list:south-list",)), cause="import")
    s.record(inst("two", region="sindh", lists=("list:south-list",)), cause="import")
    s.record(inst("tre", region="punjab", lists=("list:alpha-list",)), cause="import")


def test_parent_and_successor_kinds_follow_the_table(engine, clean):
    s = store(engine)
    seed_basic(s)
    s.record(child("admission_body", "body", "central", None, region="national"), cause="import")
    with pytest.raises(RegistryError, match="parent"):  # a seat category sits under a system, not a body
        s.record(child("seat_category", "cat", "open", "body:central"), cause="import")
    with pytest.raises(RegistryError, match="parent"):  # an official list has no parent
        s.record(replace(olist("child-list"), parent_id="body:central"), cause="import")
    with pytest.raises(RegistryError, match="successor"):  # an institution is replaced by an institution
        s.record(replace(inst("one"), status="merged", successor_id="list:alpha-list"), cause="review")
    s.record(replace(inst("one"), status="merged", successor_id="inst:two"), cause="review")


def test_search_text_is_literal(engine, clean):
    s = store(engine)
    seed_basic(s)
    s.record(replace(inst("one"), name="100% Merit_College"), cause="review")
    assert s.list(q="%") == [s.get("inst:one")]
    assert s.list(q="t_c") == [s.get("inst:one")]
    assert s.list(q="t%c") == []
    assert s.list(q="_") == [s.get("inst:one")]


def test_the_first_insert_writes_one_revision_even_when_racing(engine, clean):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    s = store(engine)
    s.record(olist(), cause="import")
    for n in range(6):
        entry = inst(f"race{n}")
        barrier = Barrier(6)

        def go(i, entry=entry, barrier=barrier):
            barrier.wait()
            return s.record(replace(entry, name=f"Race {n} writer {i}"), cause="import", actor=f"w{i}").action

        with ThreadPoolExecutor(6) as pool:
            list(pool.map(go, range(6)))
        revs = s.revisions(entry.entity_id)
        assert [r.action for r in revs].count("insert") == 1 and revs[0].action == "insert"
        assert all(a.after == b.before for a, b in zip(revs, revs[1:]))  # an unbroken chain


def test_replanner_confirmed_ignores_a_bodys_rows(engine, clean):
    """M-3: `confirmed` asks for research's own (general) rows, as the existence readers do."""
    from app.os.knowledge.port import Fact
    from app.os.knowledge.store import SqlKnowledge
    from app.os.replan.apply import Replanner
    from tests.os.registry.helpers import put

    r = object.__new__(Replanner)  # `confirmed` reads only the engine and the tenant
    r.engine, r.tenant = engine, "pai"
    k = SqlKnowledge(engine, "pai")
    put(k, "programme", "p1", "pass_mark", Fact(1, "q", "https://a.test/x", AT, 2027, "confirmed", owner_ref="body:central"))
    assert not r.confirmed("p1", 2027)
    put(k, "programme", "p1", "deadline_close", Fact(1, "q", "https://a.test/x", AT, 2027, "confirmed"))
    assert r.confirmed("p1", 2027)
