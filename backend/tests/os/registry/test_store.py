"""P2-T2: recording, reading and linking registry rows (P2 spec §4.1; R-32, R-33, R-60)."""

from dataclasses import replace

import pytest
from sqlalchemy import update

from app.os import models
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.registry.store import RegistryError

from .helpers import child, inst, olist, seed_basic, store

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
    s.link("sys:central-merit", "uses_test", "test:alpha-entry")
    s.link("sys:central-merit", "uses_test", "test:alpha-entry")  # again: no second edge
    s.link("sys:central-merit", "has_category", "cat:open-merit")
    s.link("sys:central-merit", "admits", "inst:one")
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
        s.link("sys:central-merit", "has_category", "test:alpha-entry")
    with pytest.raises(RegistryError, match="admission_system"):
        s.link("inst:one", "uses_test", "test:alpha-entry")
    with pytest.raises(RegistryError, match="exist"):
        s.link("sys:central-merit", "admits", "inst:ghost")
    with pytest.raises(RegistryError, match="exist"):
        s.link("sys:central-merit", "admits", "no-such-programme", to_kind="programme")
    with pytest.raises(ValueError, match="rel"):
        s.link("sys:central-merit", "owns", "inst:one")


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
                     family="bachelor", region="punjab")
    p = ps.get("p1")
    assert (p.institution_id, p.campus_id, p.level, p.field, p.family, p.region) == (
        "inst:one", "campus:north", "bachelor", "science", "bachelor", "punjab")
    assert s.programmes_of("inst:one") == ["p1"] and s.programmes_of("inst:two") == []
    with pytest.raises(RegistryError, match="programme"):
        s.link_programme("ghost", institution_id="inst:one")
    with pytest.raises(RegistryError, match="institution"):
        s.link_programme("p1", institution_id="inst:ghost")
    with pytest.raises(RegistryError, match="campus"):  # the campus belongs to another institution
        s.link_programme("p1", institution_id="inst:two", campus_id="campus:north")
    with pytest.raises(ValueError, match="region"):
        s.link_programme("p1", institution_id="inst:one", region="narnia")
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
