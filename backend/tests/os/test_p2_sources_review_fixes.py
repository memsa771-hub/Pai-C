"""P2-T3 review fixes (C1-C3, I1-I7, M1-M5; R-24, R-71). Fictional `.test` sites and text only."""

import ssl
import threading
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.os import models
from app.os.knowledge.sources.allowlist import (
    AllowList,
    NotApproved,
    Scope,
    SourceDomains,
    SourceEntry,
    load_allowlist,
    resolve_claims,
)
from app.os.knowledge.sources.integrity import (
    Previous,
    check_page,
    is_tls_failure,
    load_config,
)
from app.os.knowledge.sources.suspect import SourceGuard
from app.os.knowledge.store import SqlKnowledge
from app.os.settings import load_settings
from tests.os.fixture_sites.server import Resource
from tests.os.test_p2_sources_gateway import ALPHA, FIX, NORTH, build, fact

pytestmark = pytest.mark.req("R-24", "R-71")
ON = lambda url: "own.test" in url


def codes(text, links=(), previous=None):
    return [f.code for f in check_page(text, list(links), ON, previous)]


def events(engine, kind):
    with engine.connect() as conn:
        return conn.execute(select(models.events.c.payload).where(models.events.c.type == kind)
                            .order_by(models.events.c.id)).scalars().all()


def entry(domain, region="north_region", family="university", ref="", tier="institution"):
    return SourceEntry(domain, region, family, "", ref, tier, "https://list.test/", "tester")


# --- C1: never a two-label fallback ---------------------------------------------------------------------------------

def test_c1_an_unlisted_host_under_a_three_label_suffix_flags_only_that_host(engine, clean):
    k = SqlKnowledge(engine, "pai")
    spam = k.upsert("programme", "p1", "fee", fact("https://admissions.spam-inst.edu.xy/fees"))
    other = k.upsert("programme", "p2", "fee", fact("https://other-inst.edu.xy/fees"))
    g = SourceGuard(engine, "pai")
    case = g.flag("https://admissions.spam-inst.edu.xy/page", "spam")
    assert case.domain == "admissions.spam-inst.edu.xy"
    assert g.is_suspect("https://admissions.spam-inst.edu.xy/x")
    assert not g.is_suspect("https://other-inst.edu.xy/x") and not g.is_suspect("https://edu.xy/")
    assert not g.is_suspect("https://spam-inst.edu.xy/")
    assert k.get(spam)[3].status == "unconfirmed" and k.get(other)[3].status == "confirmed"


def test_c1_a_listed_host_flags_its_listed_domain(engine, clean):
    g = SourceGuard(engine, "pai")
    g.domains.sync(AllowList((entry("inst.edu.xy"),), {}, frozenset()))
    assert g.flag("https://www.admissions.inst.edu.xy/p", "spam").domain == "inst.edu.xy"


# --- C2: link flood needs a previous clean snapshot -------------------------------------------------------------------

def test_c2_no_link_flood_without_a_previous_snapshot():
    off = [(f"https://off{i}.test/", "x") for i in range(40)]
    assert codes("Recognised institutions", off) == []
    grew = Previous("Recognised institutions", links_total=40, links_off_list=2)
    assert codes("Recognised institutions", off, previous=grew) == ["link_flood"]


def test_c2_a_regulator_list_page_is_a_baseline_not_a_flood(engine, clean, fixture_sites):
    reg = "www.higher-ed-regulator.test"
    insts = [f"inst{i}.test" for i in range(35)]
    links = "".join(f"<a href='https://{h}/'>Institution {i}</a>" for i, h in enumerate(insts))
    fixture_sites.set_page(reg, "/recognised", f"<html><body><h1>Recognised institutions</h1>{links}</body></html>")
    gw, g, _ = build(engine, fixture_sites)
    page = gw.fetch(fixture_sites.url(reg, "/recognised"), [], [], NORTH)
    assert page.ok and g.domains.state_of(reg).state == "active"
    assert g.snapshots.get(page.snapshot_id).flagged is None  # the baseline


def test_c2_links_to_hosts_listed_in_any_scope_are_not_off_list(engine, clean, fixture_sites):
    reg = "www.higher-ed-regulator.test"
    insts = [f"inst{i}.test" for i in range(35)]
    g0 = SourceDomains(engine, "pai")
    g0.sync(AllowList(tuple(entry(h, region="south_region") for h in insts), {}, frozenset()))
    fixture_sites.set_page(reg, "/recognised", "<html><body><h1>Recognised institutions</h1></body></html>")
    gw, g, clock = build(engine, fixture_sites)
    assert gw.fetch(fixture_sites.url(reg, "/recognised"), [], [], NORTH).ok
    links = "".join(f"<a href='https://www.{h}/'>Institution {i}</a>" for i, h in enumerate(insts))
    fixture_sites.set_page(reg, "/recognised", f"<html><body><h1>Recognised institutions</h1>{links}</body></html>")
    clock.now += timedelta(days=2)
    assert gw.fetch(fixture_sites.url(reg, "/recognised"), [], [], NORTH).ok
    assert g.domains.state_of(reg).state == "active"


# --- C3: ordinary admission text is not spam ----------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Book a time slot for your interview. Few slots remain for the morning session.",
    "Interview slots: choose a slot online. The jackpot of hard work is a merit seat.",
    "Students who win the poker-faced debate prize get a free uniform.",
])
def test_c3_ordinary_admission_text_is_not_spam(text):
    assert codes(text) == []


def test_c3_one_stem_counts_once():
    cfg = load_config()
    assert codes("casino casinos") == []  # one stem
    grouped = [t for t in cfg["spam"]["terms"]["en"] if isinstance(t, list)]
    assert grouped, "variants of one stem are grouped in the data file"


def test_c3_url_terms_match_on_token_boundaries():
    links = [("https://occasional-bettingham.test/occasion", "x"), ("https://pokerfield.test/", "y")]
    assert codes("Welcome", links) == []  # 'casino' inside 'occasional', 'betting' inside 'bettingham'
    assert codes("Welcome", [("https://x.test/casino/betting", "go")]) == ["spam"]
    assert codes("Welcome", [("https://x.test/free-spins", "a"), ("https://y.test/casino", "b")]) == ["spam"]


# --- I1: final URL and is_listed --------------------------------------------------------------------------------

def test_i1_redirect_to_a_suspect_domain_is_refused(engine, clean, fixture_sites):
    gw, g, _ = build(engine, fixture_sites)
    g.domains.mark_suspect("beta-college.test", "spam")
    fixture_sites._sites[ALPHA]["/go"] = Resource(b"", "text/html", 302, "https://beta-college.test/admissions")
    assert gw.fetch(fixture_sites.url(ALPHA, "/go"), [], [], NORTH).blocked == "suspect_domain"


def test_i1_is_listed_refuses_a_domain_with_any_suspect_row(engine, clean):
    d = SourceDomains(engine, "pai")
    d.sync(AllowList((entry("two-scope.test"), entry("two-scope.test", region="south_region")), {}, frozenset()))
    with d.engine.begin() as conn:
        conn.execute(models.source_domains.update().where(models.source_domains.c.region == "south_region")
                     .values(state="suspect", state_reason="spam"))
    assert not d.is_listed("two-scope.test", NORTH)


# --- I2: atomic, idempotent, race-safe --------------------------------------------------------------------------

def test_i2_two_threads_run_the_flow_once(engine, clean):
    k = SqlKnowledge(engine, "pai")
    ids = [k.upsert("programme", f"p{i}", "fee", fact(f"https://race.test/f{i}")) for i in range(5)]
    cases, barrier, out, errors = [], threading.Barrier(2), [], []
    g = SourceGuard(engine, "pai", on_suspect=cases.append)

    def run():
        barrier.wait()
        try:
            out.append(g.flag("https://race.test/x", "spam"))
        except Exception as e:  # noqa: BLE001 - a lost race must not raise
            errors.append(e)
    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert sum(1 for c in out if c is not None) == 1 and len(cases) == 1
    assert len(events(engine, "source_suspect")) == 1
    for i in ids:
        assert k.get(i)[3].status == "unconfirmed"
        assert sum(1 for r in k.revisions(i) if r.action == "status") == 1
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.source_domains)).scalar_one() == 1


def test_i2_a_rerun_on_a_suspect_domain_completes_the_drop(engine, clean):
    k = SqlKnowledge(engine, "pai")
    g = SourceGuard(engine, "pai")
    g.domains.mark_suspect("half.test", "spam")  # the flow stopped after the state change
    fid = k.upsert("programme", "p", "fee", fact("https://half.test/f"))
    assert g.flag("https://half.test/x", "spam") is None  # not a new case
    assert k.get(fid)[3].status == "unconfirmed"


# --- I3: the one-body rule also applies to existing rows ---------------------------------------------------------

def test_i3_a_second_domain_for_an_existing_body_flags_through_the_flow(engine, clean):
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "p", "fee", fact("https://x-college.test/f"))
    g = SourceGuard(engine, "pai")
    one = AllowList((entry("x-college.test", ref="body-x"),), {"body-x": ("edu.test",)}, frozenset())
    assert g.sync(one).suspect == ()
    both = AllowList((entry("x-college.test", ref="body-x"), entry("x-college.edu.test", ref="body-x")),
                     {"body-x": ("edu.test",)}, frozenset())
    r = g.sync(both)
    assert r.suspect == (("x-college.test", "duplicate_claim:body-x"),)
    assert g.domains.state_of("x-college.test").state == "suspect"
    assert k.get(fid)[3].status == "unconfirmed"
    assert len(events(engine, "source_suspect")) == 1
    again = g.sync(both)
    assert again.suspect == () and (again.added, again.updated) == (0, 0)  # only rows that changed


# --- I4: remove_missing keeps suspect rows ---------------------------------------------------------------------

def test_i4_remove_missing_keeps_a_suspect_tombstone_and_readding_stays_suspect(engine, clean):
    d = SourceDomains(engine, "pai")
    d.sync(AllowList((entry("gone.test"), entry("kept.test")), {}, frozenset()))
    d.mark_suspect("gone.test", "spam")
    r = d.sync(AllowList((entry("kept.test"),), {}, frozenset()), remove_missing=True)
    assert r.removed == 0
    assert d.state_of("gone.test").state == "suspect"
    assert not d.is_listed("gone.test", NORTH)
    d.sync(AllowList((entry("kept.test"), entry("gone.test")), {}, frozenset()))
    assert d.state_of("gone.test").state == "suspect"
    d.sync(AllowList((entry("kept.test"), entry("gone.test", region="south_region")), {}, frozenset()))
    assert d.state_of("gone.test").state == "suspect"
    assert not d.is_listed("gone.test", Scope(region="south_region", family="university"))


# --- I5: only certificate verification failures -------------------------------------------------------------

def test_i5_only_certificate_verification_failures_count():
    other = httpx.ConnectError("[SSL: WRONG_VERSION_NUMBER] wrong version number")
    other.__cause__ = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")
    assert not is_tls_failure(other)
    eof = httpx.ConnectError("eof")
    eof.__cause__ = ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
    assert not is_tls_failure(eof)
    for msg in ("certificate verify failed: Hostname mismatch", "certificate has expired"):
        e = httpx.ConnectError(msg)
        e.__cause__ = ssl.SSLCertVerificationError(1, msg)
        assert is_tls_failure(e)


# --- I6: https only with the guard ----------------------------------------------------------------------------

def test_i6_http_is_refused_with_the_guard(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    fixture_sites.requests.clear()
    assert gw.fetch(f"http://{ALPHA}/admissions/notice", [], [], NORTH).blocked == "insecure_scheme"
    assert fixture_sites.requests == []
    fixture_sites._sites[ALPHA]["/down"] = Resource(b"", "text/html", 302, f"http://{ALPHA}/admissions/notice")
    assert gw.fetch(fixture_sites.url(ALPHA, "/down"), [], [], NORTH).blocked == "insecure_scheme"


# --- I7: normalised approvers and an event ---------------------------------------------------------------------

def test_i7_approver_ids_are_normalised_and_reactivation_is_recorded(engine, clean):
    d = SourceDomains(engine, "pai")
    d.sync(load_allowlist(FIX))
    d.mark_suspect("alpha-university.test", "spam")
    seen = []

    def is_approver(i):
        seen.append(i)
        return i in {"ann", "bob"}
    with pytest.raises(NotApproved):
        d.reactivate("alpha-university.test", requested_by="Ann", approved_by=" ANN ", is_approver=is_approver)
    assert d.reactivate("alpha-university.test", requested_by=" Ann", approved_by="BOB ", is_approver=is_approver)
    assert set(seen) <= {"ann", "bob"}
    ev = events(engine, "source_reactivated")
    assert len(ev) == 1 and ev[0]["domain"] == "alpha-university.test"
    assert sorted(ev[0]["approvers"]) == ["ann", "bob"]


# --- M1, M2, M4, M5 ---------------------------------------------------------------------------------------------

def test_m1_preferred_suffix_needs_a_label_boundary():
    allow = AllowList((entry("x.edu.test", ref="b"), entry("x-notedu.test", ref="b")), {"b": ("edu.test",)},
                      frozenset())
    assert resolve_claims(allow) == {"x-notedu.test": "duplicate_claim:b"}
    tricky = AllowList((entry("x.edu.test", ref="b"), entry("xedu.test", ref="b")), {"b": ("edu.test",)}, frozenset())
    assert resolve_claims(tricky) == {"xedu.test": "duplicate_claim:b"}


def test_m2_updated_and_revised_do_not_explain_a_wholesale_change():
    prev = Previous(" ".join(f"word{i}" for i in range(60)), 0, 0)
    other = " ".join(f"other{i}" for i in range(60))
    assert codes("Updated: " + other, previous=prev) == ["wholesale_change"]
    assert codes("Revised " + other, previous=prev) == ["wholesale_change"]


def test_m4_the_worker_flag_is_a_setting():
    assert load_settings({"DATABASE_URL": "x"}).source_guard is False
    assert load_settings({"DATABASE_URL": "x", "OS_SOURCE_GUARD": "1"}).source_guard is True


def test_m5_a_snapshot_whose_original_was_too_large_is_marked(engine, clean):
    g = SourceGuard(engine, "pai")
    g.snapshots.max_bytes = 10
    got = g.inspect("https://own.test/a.pdf", "text", [], content_type="application/pdf", fetched_at=None,
                    is_official=lambda u: True, original=b"x" * 50, original_type="application/pdf")
    snap = g.snapshots.get(got.snapshot_id)
    assert snap.original_too_large is True and g.snapshots.original(got.snapshot_id) is None


def test_m3_the_suspect_flow_runs_outside_the_page_lock(engine, clean, fixture_sites):
    seen = []
    gw, g, _ = build(engine, fixture_sites)

    def hook(case):
        with engine.connect() as conn:  # the page row is visible: the page transaction has committed
            seen.append(conn.execute(select(func.count()).select_from(models.pages)
                                     .where(models.pages.c.url == case.url)).scalar_one())
    g.on_suspect = hook
    gw.fetch(fixture_sites.url("beta-college.test", "/admissions"), [], [], NORTH)
    assert seen == [1]
