"""P2-T1: the local fixture server for fictional official-looking sites (P2 spec §5, "no data from memory")."""

from datetime import UTC, datetime

import httpx
import pytest

from app.os.knowledge.research.pages import PageGateway
from app.os.settings import load_settings
from tests.os.fixture_sites.server import load_sites

UNI = "www.alpha-university.test"


def test_every_host_is_reserved_test_tld():
    sites = load_sites()
    assert sites and all(h.endswith(".test") for h in sites)


def test_serves_by_host(fixture_sites):
    with fixture_sites.client() as c:
        r = c.get(fixture_sites.url(UNI, "/admissions/notice"))
        assert r.status_code == 200 and "Applications close on 1 August 2027." in r.text
        assert "online casino bonus" in c.get(fixture_sites.url("beta-college.test", "/admissions")).text
        assert c.get(fixture_sites.url("nobody.test", "/")).status_code == 404
        assert "Disallow: /private" in c.get(fixture_sites.url(UNI, "/robots.txt")).text
        moved = c.get(fixture_sites.url(UNI, "/moved"))
        assert str(moved.url) == "https://elsewhere.test/page"
    assert (UNI, "/admissions/notice") in fixture_sites.requests


def test_refuses_real_hosts(fixture_sites):
    with fixture_sites.client() as c, pytest.raises(httpx.ConnectError):
        c.get("https://example.com/")


def test_set_page_and_reset(fixture_sites):
    fixture_sites.set_page(UNI, "/admissions/notice", "<p>Applications close on 9 August 2027.</p>")
    with fixture_sites.client() as c:
        assert "9 August" in c.get(fixture_sites.url(UNI, "/admissions/notice")).text
        fixture_sites.reset()
        assert "1 August" in c.get(fixture_sites.url(UNI, "/admissions/notice")).text


def test_page_gateway_reads_a_fixture_site(engine, clean, fixture_sites):
    settings = load_settings({"DATABASE_URL": "x"})
    now = datetime(2027, 5, 2, 10, tzinfo=UTC)
    gw = PageGateway(engine, "pai", settings, client=fixture_sites.client(), clock=lambda: now, sleep=lambda s: None)
    page = gw.fetch(fixture_sites.url(UNI, "/admissions/notice"), ["alpha-university.test"], [])
    assert page.blocked is None and "Applications close on 1 August 2027." in page.text
    private = gw.fetch(fixture_sites.url(UNI, "/private/page"), ["alpha-university.test"], [])
    assert private.blocked
