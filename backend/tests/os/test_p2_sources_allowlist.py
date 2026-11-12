"""P2-T3: the allow-list loader, `os_source_domains` and the suspect state (R-24, R-71). Fictional data."""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.sources.allowlist import (
    AllowList,
    AllowListError,
    NotApproved,
    Scope,
    SourceDomains,
    SourceEntry,
    host_matches,
    load_allowlist,
    resolve_claims,
    seed_route_entries,
)

pytestmark = pytest.mark.req("R-24", "R-71")
FIX = Path(__file__).parent / "fixtures" / "sources"
NORTH = Scope(region="north_region", family="university")


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_load_fixture_lists():
    allow = load_allowlist(FIX)
    domains = {(e.domain, e.region, e.route_key) for e in allow.entries}
    assert ("alpha-university.test", "north_region", "") in domains
    assert ("exam-board.test", "", "route_one") in domains
    assert all(e.list_ref and e.reviewed_by for e in allow.entries)


def test_committed_lists_directory_loads_and_holds_no_unreviewed_entry():
    assert all(e.list_ref and e.reviewed_by for e in load_allowlist().entries)


@pytest.mark.parametrize("body, why", [
    ("region: r\nbodies: []\n", "family"),
    ("region: r\nroute_key: x\nfamily: f\nbodies: []\n", "exactly one"),
    ("region: R1\nfamily: f\nbodies: []\n", "snake case"),
    ("region: r\nfamily: f\nbodies: [{tier: nope, domains: [a.test], list_ref: x, reviewed_by: y}]\n", "tier"),
    ("region: r\nfamily: f\nbodies: [{tier: board, domains: [a.test], reviewed_by: y}]\n", "list_ref"),
    ("region: r\nfamily: f\nbodies: [{tier: board, domains: [a.test], list_ref: x}]\n", "reviewed_by"),
    ("region: r\nfamily: f\nbodies: [{tier: board, domains: ['https://a.test/'], list_ref: x, reviewed_by: y}]\n",
     "bare domain"),
    ("region: r\nfamily: f\nbodies: [{tier: board, domains: [a.test, A.test], list_ref: x, reviewed_by: y}]\n",
     "twice"),
])
def test_bad_lists_are_refused(tmp_path, body, why):
    with pytest.raises(AllowListError, match=why):
        load_allowlist(_write(tmp_path, "x.yaml", body))


def test_sync_lookup_and_subdomains(engine, clean):
    store = SourceDomains(engine, "pai")
    r = store.sync(load_allowlist(FIX))
    assert (r.added, r.updated, r.suspect) == (4, 0, ())
    assert store.sync(load_allowlist(FIX)).added == 0
    assert store.is_listed("www.alpha-university.test", NORTH)
    assert not store.is_listed("alpha-university.test", Scope(region="south_region", family="university"))
    assert not store.is_listed("alpha-university.test", Scope(region="north_region", family="board"))
    assert not store.is_listed("evil-alpha-university.test", NORTH)  # not a subdomain
    assert store.is_listed("exam-board.test", Scope(route_key="route_one"))
    assert store.state_of("unknown.test") is None
    assert host_matches("a.b.test", "b.test") and not host_matches("ab.test", "b.test")


def test_suspect_survives_resync_and_needs_two_approvers(engine, clean):
    store = SourceDomains(engine, "pai")
    store.sync(load_allowlist(FIX))
    assert store.mark_suspect("alpha-university.test", "spam") is True
    assert store.mark_suspect("alpha-university.test", "spam") is False
    st = store.state_of("www.alpha-university.test")
    assert (st.state, st.reason) == ("suspect", "spam")
    assert not store.is_listed("alpha-university.test", NORTH)
    store.sync(load_allowlist(FIX))
    assert store.state_of("alpha-university.test").state == "suspect"
    approvers = {"ann", "bob"}.__contains__
    for a, b in (("ann", "ann"), ("", "bob"), ("ann", "")):
        with pytest.raises(NotApproved):
            store.reactivate("alpha-university.test", requested_by=a, approved_by=b, is_approver=approvers)
    with pytest.raises(NotApproved):
        store.reactivate("alpha-university.test", requested_by="ann", approved_by="cat", is_approver=approvers)
    assert store.state_of("alpha-university.test").state == "suspect"
    assert store.reactivate("alpha-university.test", requested_by="ann", approved_by="bob",
                            is_approver=approvers) == 1
    assert store.state_of("alpha-university.test").state == "active"


def test_flag_row_for_an_unlisted_domain(engine, clean):
    store = SourceDomains(engine, "pai")
    assert store.mark_suspect("legacy-site.test", "tls_invalid")
    assert store.state_of("www.legacy-site.test").state == "suspect"
    assert store.reactivate("legacy-site.test", requested_by="a", approved_by="b", is_approver=lambda _: True)
    assert store.state_of("legacy-site.test") is None  # no entry to return to
    with engine.connect() as conn:
        assert conn.execute(select(models.source_domains.c.id)).first() is None


def _claims(tmp_path, preferred, extra=""):
    body = f"""region: north_region
family: university
bodies:
  - body_ref: body-x
    tier: institution
    domains: [x-college.edu.test, x-college.test]
    list_ref: "https://list.test/"
    reviewed_by: t
    preferred_suffixes: {preferred}
    {extra}
"""
    return load_allowlist(_write(tmp_path, "c.yaml", body))


def test_two_domains_one_body_the_preferred_suffix_stays(engine, clean, tmp_path):
    allow = _claims(tmp_path, "[edu.test]")
    assert resolve_claims(allow) == {"x-college.test": "duplicate_claim:body-x"}
    store = SourceDomains(engine, "pai")
    assert store.sync(allow).suspect == (("x-college.test", "duplicate_claim:body-x"),)
    assert store.state_of("x-college.edu.test").state == "active"
    assert store.state_of("x-college.test").state == "suspect"


def test_no_single_preferred_means_both_suspect_unless_a_reviewer_confirmed(tmp_path):
    assert set(resolve_claims(_claims(tmp_path, "[]")).values()) == {"ambiguous_claim:body-x"}
    assert resolve_claims(_claims(tmp_path, "[]", "multiple_domains_ok: true")) == {}


def test_route_seed_entries_load_as_allow_list(engine, clean):
    entries = seed_route_entries("route_one", ["Old-Board.test"], list_ref="profile:official_sources",
                                 reviewed_by="seed")
    store = SourceDomains(engine, "pai")
    store.sync(AllowList(tuple(entries), {}, frozenset()))
    assert store.is_listed("old-board.test", Scope(route_key="route_one"))
    assert entries[0] == SourceEntry("old-board.test", route_key="route_one", tier="institution",
                                     list_ref="profile:official_sources", reviewed_by="seed")
