"""P2-T3: the page gateway with the source guard, and the spam fixture proof (R-24, R-71, R-29). Fictional `.test` sites."""

import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.os import models
from app.os.knowledge.port import Fact
from app.os.knowledge.research.pages import PageGateway, TransientFetchError
from app.os.knowledge.sources.allowlist import (
    Scope,
    SourceDomains,
    load_allowlist,
)
from app.os.knowledge.sources.suspect import SourceGuard
from app.os.knowledge.store import SqlKnowledge
from app.os.settings import load_settings
from tests.os.test_research_pages import minimal_pdf

pytestmark = pytest.mark.req("R-24", "R-71", "R-29")
FIX = Path(__file__).parent / "fixtures" / "sources"
NORTH = Scope(region="north_region", family="university")
ALPHA, BETA = "www.alpha-university.test", "beta-college.test"
T0 = datetime(2027, 5, 2, 10, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def build(engine, sites, *, guard=True, after=None, hook=None, client=None, clock=None):
    clock = clock or Clock()
    settings = load_settings({"DATABASE_URL": "x"})
    g = None
    if guard:
        SourceDomains(engine, "pai").sync(load_allowlist(FIX))
        g = SourceGuard(engine, "pai", after_change=after, on_suspect=hook)
    gw = PageGateway(engine, "pai", settings, client=client or sites.client(), clock=clock, sleep=lambda s: None,
                     sources=g)
    return gw, g, clock


def rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def fact(url, status="confirmed"):
    return Fact(value="x", quote="q", url=url, checked_at=T0, intake_year=2027, status=status)


# --- without the guard: as before -----------------------------------------------------------------------------------

def test_without_a_guard_nothing_changes(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites, guard=False)
    page = gw.fetch(fixture_sites.url(BETA, "/admissions"), [BETA], [])
    assert page.ok and page.blocked is None and page.snapshot_id is None  # the spam page is read as before
    assert rows(engine, models.page_snapshots) == 0
    assert gw.fetch(fixture_sites.url(ALPHA, "/admissions/notice"), [], [], NORTH).blocked == "not_official"


# --- allow-list lookup ----------------------------------------------------------------------------------------------

def test_listed_domains_are_official_for_their_scope(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    url = fixture_sites.url(ALPHA, "/admissions/notice")
    assert gw.fetch(url, [], [], NORTH).ok
    p1, p2, p3 = (fixture_sites.url(ALPHA, f"/admissions/{n}") for n in ("portal", "apply", "notice2"))
    assert gw.fetch(p1, [], []).blocked == "not_official"  # no scope, no old list
    assert gw.fetch(p2, [], [], Scope(region="south_region", family="university")).blocked == "not_official"
    fixture_sites.set_page(ALPHA, "/admissions/notice2", "<html><body>Hello</body></html>")
    assert gw.fetch(p3, ["alpha-university.test"], []).ok  # the old per-programme lists keep working
    assert gw.fetch(fixture_sites.url("elsewhere.test", "/page"), [], [], NORTH).blocked == "not_official"


def test_redirect_off_the_list_is_still_refused(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    assert gw.fetch(fixture_sites.url(ALPHA, "/moved"), [], [], NORTH).blocked == "redirect_not_official"
    assert rows(engine, models.page_snapshots) == 0


# --- snapshots -----------------------------------------------------------------------------------------------------

def test_every_read_page_has_a_snapshot(engine, clean, fixture_sites):
    gw, g, _ = build(engine, fixture_sites)
    page = gw.fetch(fixture_sites.url(ALPHA, "/admissions/notice"), [], [], NORTH)
    snap = g.snapshots.get(page.snapshot_id)
    assert snap.text == page.text and snap.read_method == "fetch" and snap.flagged is None
    assert snap.content_type.startswith("text/html") and snap.links_total == 1


def test_pdf_original_is_kept_with_its_snapshot(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/notice.pdf", minimal_pdf("Closing date 1 August"), "application/pdf")
    gw, g, _ = build(engine, fixture_sites)
    page = gw.fetch(fixture_sites.url(ALPHA, "/notice.pdf"), [], [], NORTH)
    assert page.ok and "Closing date" in page.text
    assert g.snapshots.original(page.snapshot_id)[1] == "application/pdf"


# --- the spam proof (spec §4.2 "Proof", master R-71) ----------------------------------------------------------------

def test_spam_fixture_is_refused_and_its_domain_becomes_suspect(engine, clean, fixture_sites):
    k = SqlKnowledge(engine, "pai")
    on_beta = k.upsert("programme", "beta-bs", "deadline", fact("https://beta-college.test/old"))
    on_beta2 = k.upsert("programme", "beta-bs", "fee", fact("https://admissions.beta-college.test/fees", "verified"))
    on_alpha = k.upsert("programme", "alpha-bs", "deadline", fact("https://alpha-university.test/d"))
    changed, cases = [], []
    gw, g, _ = build(engine, fixture_sites, after=lambda *a: changed.append(a), hook=cases.append)

    page = gw.fetch(fixture_sites.url(BETA, "/admissions"), [], [], NORTH)

    assert page.blocked == "integrity:spam" and not page.ok and page.text == ""
    assert g.domains.state_of(BETA).state == "suspect"
    assert g.domains.state_of(BETA).reason == "spam"
    # its facts drop to unconfirmed, with a revision; other domains are untouched
    assert k.get(on_beta)[3].status == "unconfirmed" and k.get(on_beta2)[3].status == "unconfirmed"
    assert k.get(on_alpha)[3].status == "confirmed"
    last = k.revisions(on_beta2)[-1]
    assert (last.action, last.cause, last.cause_ref, last.after["status"]) == ("status", "monitor",
                                                                             "source:beta-college.test", "unconfirmed")
    assert sorted(c[3] for c in changed) == sorted([on_beta, on_beta2]) and all(c[4] == "unconfirmed" for c in changed)
    # a review hook and an event
    assert len(cases) == 1 and cases[0].domain == BETA and cases[0].snapshot_id == page.snapshot_id
    with engine.connect() as conn:
        ev = conn.execute(select(models.events.c.payload).where(models.events.c.type == "source_suspect")).scalars().all()
    assert len(ev) == 1 and ev[0]["domain"] == BETA and sorted(ev[0]["facts_dropped"]) == sorted([on_beta, on_beta2])
    # the evidence is a flagged snapshot the review queue can show
    snap = g.snapshots.get(page.snapshot_id)
    assert snap.flagged == "spam" and "casino" in snap.text.lower()
    # nothing new is taken from it: refused before the cache and the network, for every page
    fixture_sites.requests.clear()
    again = gw.fetch(fixture_sites.url(BETA, "/admissions"), [BETA], [], NORTH)
    other = gw.fetch(fixture_sites.url(BETA, "/other"), [BETA], [BETA], NORTH)
    assert again.blocked == other.blocked == "suspect_domain"
    assert fixture_sites.requests == []
    assert len(cases) == 1  # one review item, not one per fetch


def test_only_two_approvers_bring_a_suspect_domain_back(engine, clean, fixture_sites):
    gw, g, clock = build(engine, fixture_sites)
    gw.fetch(fixture_sites.url(BETA, "/admissions"), [], [], NORTH)
    fixture_sites.set_page(BETA, "/admissions", "<html><body><p>Merit is based on school marks.</p></body></html>")
    ok = {"ann", "bob"}.__contains__
    assert g.domains.reactivate(BETA, requested_by="ann", approved_by="bob", is_approver=ok) == 1
    clock.now += timedelta(minutes=1)  # inside the cache TTL: the old integrity block must not be served
    page = gw.fetch(fixture_sites.url(BETA, "/admissions"), [], [], NORTH)
    assert page.ok and "school marks" in page.text


def test_hidden_links_are_not_needed_for_spam_text_alone_also_counts(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/admissions/notice",
                           "<html><body><p>Cheap online casino with betting and a big jackpot</p></body></html>")
    gw, g, _ = build(engine, fixture_sites)
    assert gw.fetch(fixture_sites.url(ALPHA, "/admissions/notice"), [], [], NORTH).blocked == "integrity:spam"
    assert g.domains.state_of("alpha-university.test").state == "suspect"


# --- other integrity checks -----------------------------------------------------------------------------------------

def test_link_flood_marks_the_domain_suspect(engine, clean, fixture_sites):
    links = "".join(f"<a href='https://site{i}.test/'>read {i}</a>" for i in range(14))
    fixture_sites.set_page(ALPHA, "/links", f"<html><body><p>Admissions</p>{links}</body></html>")
    gw, g, _ = build(engine, fixture_sites)
    assert gw.fetch(fixture_sites.url(ALPHA, "/links"), [], [], NORTH).blocked == "integrity:link_flood"
    assert g.domains.state_of(ALPHA).reason == "link_flood"


def test_wholesale_change_without_a_notice_marks_the_domain_suspect(engine, clean, fixture_sites):
    old = " ".join(f"<p>{'old' + str(i) + ' ' + 'word' * 3}</p>" for i in range(50))
    new = " ".join(f"<p>{'fresh' + str(i) + ' ' + 'other' * 2}</p>" for i in range(50))
    fixture_sites.set_page(ALPHA, "/info", f"<html><body>{old}</body></html>")
    gw, g, clock = build(engine, fixture_sites)
    assert gw.fetch(fixture_sites.url(ALPHA, "/info"), [], [], NORTH).ok
    fixture_sites.set_page(ALPHA, "/info", f"<html><body>{new}</body></html>")
    clock.now += timedelta(days=2)  # past the page cache
    page = gw.fetch(fixture_sites.url(ALPHA, "/info"), [], [], NORTH)
    assert page.blocked == "integrity:wholesale_change"
    assert g.domains.state_of(ALPHA).state == "suspect"


def test_a_normal_update_with_a_notice_passes(engine, clean, fixture_sites):
    old = " ".join(f"<p>{'old' + str(i) + ' ' + 'word' * 3}</p>" for i in range(50))
    new = " ".join(f"<p>{'fresh' + str(i) + ' ' + 'other' * 2}</p>" for i in range(50))
    fixture_sites.set_page(ALPHA, "/info", f"<html><body>{old}</body></html>")
    gw, g, clock = build(engine, fixture_sites)
    assert gw.fetch(fixture_sites.url(ALPHA, "/info"), [], [], NORTH).ok
    fixture_sites.set_page(ALPHA, "/info", f"<html><body><h1>New notice</h1>{new}</body></html>")
    clock.now += timedelta(days=2)
    assert gw.fetch(fixture_sites.url(ALPHA, "/info"), [], [], NORTH).ok
    assert g.domains.state_of(ALPHA).state == "active"


def _tls_client():
    def handler(request):
        inner = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED: certificate has expired")
        err = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]", request=request)
        err.__cause__ = inner
        raise err
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_invalid_tls_is_recorded_and_flags_the_domain(engine, clean, fixture_sites):
    cases = []
    gw, g, _ = build(engine, fixture_sites, client=_tls_client(), hook=cases.append)
    page = gw.fetch(fixture_sites.url(ALPHA, "/admissions/notice"), [], [], NORTH)
    assert page.blocked == "tls_invalid"
    assert g.domains.state_of(ALPHA).reason == "tls_invalid" and len(cases) == 1
    assert gw.fetch(fixture_sites.url(ALPHA, "/x"), [], [], NORTH).blocked == "suspect_domain"


def test_without_a_guard_a_tls_failure_is_a_transient_error_as_before(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites, guard=False, client=_tls_client())
    with pytest.raises(TransientFetchError):
        gw.fetch(fixture_sites.url(ALPHA, "/admissions/notice"), ["alpha-university.test"], [])


def test_worker_builds_a_guard_only_when_switched_on(engine, clean, monkeypatch):
    from app.os.kernel import Kernel
    from app.os.runner.worker import _source_guard

    settings = load_settings({"DATABASE_URL": "x"})
    kernel = Kernel(engine, settings.tenant_id)
    monkeypatch.delenv("OS_SOURCE_GUARD", raising=False)
    assert _source_guard(settings, engine, kernel) is None
    monkeypatch.setenv("OS_SOURCE_GUARD", "1")
    guard = _source_guard(settings, engine, kernel)
    assert guard is not None and guard.snapshots.max_bytes == settings.page_max_bytes
    assert guard.after_change is not None
