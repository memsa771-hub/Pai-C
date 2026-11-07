"""P2-T4: the headless render fallback for JavaScript pages (P2-D12; R-74). Fictional `.test` sites, a real headless
Chromium when one can be found (set OS_RENDER_BROWSER to point at one); the browser tests skip otherwise."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.render import (
    PlaywrightRenderer,
    RenderFailed,
    find_browser,
    looks_like_js_shell,
)
from app.os.knowledge.sources.allowlist import Scope, SourceDomains, load_allowlist
from app.os.knowledge.sources.suspect import SourceGuard
from app.os.settings import load_settings

pytestmark = pytest.mark.req("R-74")
ALPHA, OWN = "www.alpha-university.test", ["alpha-university.test"]
NOW = datetime(2027, 5, 2, 10, tzinfo=UTC)
BROWSER = find_browser(os.environ.get("OS_RENDER_BROWSER", ""),
                       "/opt/pw-browsers/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
                       "/usr/bin/google-chrome", "/usr/bin/chromium")
needs_browser = pytest.mark.skipif(BROWSER is None or not PlaywrightRenderer(browser_path=BROWSER).available(),
                                   reason="no headless Chromium found")
SHELL = ("<html><head><script src='/static/notice.js'></script></head><body><div id='root'></div>"
         "<noscript>You need to enable JavaScript.</noscript></body></html>")
SCRIPT = ("fetch('/api/notice.json').then(r => r.json()).then(d => {"
          "document.getElementById('root').innerHTML = '<h1>' + d.title + '</h1><p>' + d.line + '</p>'; });")


def gateway(engine, sites, renderer, **kw):
    return PageGateway(engine, "pai", load_settings({"DATABASE_URL": "x"}), client=sites.client(), clock=lambda: NOW,
                       sleep=lambda s: None, renderer=renderer, **kw)


def portal(sites, script=SCRIPT):
    sites.set_page(ALPHA, "/portal", SHELL)
    sites.set_page(ALPHA, "/static/notice.js", script, "application/javascript")
    sites.set_page(ALPHA, "/api/notice.json", '{"title": "Fall 2027 notice", "line": "Applications close on 1 August 2027."}',
                   "application/json")
    return f"https://{ALPHA}/portal"


def test_shell_detection_uses_visible_text_and_scripts():
    assert looks_like_js_shell(SHELL, "", 200)
    assert not looks_like_js_shell(SHELL, "x" * 300, 200)
    assert not looks_like_js_shell("<html><body>Closed</body></html>", "Closed", 200)  # short but no scripts


def test_without_a_renderer_a_shell_is_read_as_before(engine, clean, fixture_sites):
    url = portal(fixture_sites)
    page = gateway(engine, fixture_sites, None).fetch(url, OWN, [])
    assert page.text == "" and page.blocked is None and page.read_method == "fetch"


@needs_browser
def test_a_shell_is_rendered_and_read(engine, clean, fixture_sites):
    url = portal(fixture_sites)
    gw = gateway(engine, fixture_sites, PlaywrightRenderer(browser_path=BROWSER))
    page = gw.fetch(url, OWN, [])
    assert page.ok and page.read_method == "render"
    assert "Applications close on 1 August 2027." in page.text and "Fall 2027 notice" in page.text
    again = gw.fetch(url, OWN, [])  # the cache keeps how it was read
    assert again.from_cache and again.read_method == "render"


@needs_browser
def test_the_browser_can_only_reach_what_the_allow_list_accepts(engine, clean, fixture_sites):
    script = SCRIPT + "var i = new Image(); i.src = 'https://elsewhere.test/pixel.gif'; fetch('https://elsewhere.test/x');"
    url = portal(fixture_sites, script)
    gw = gateway(engine, fixture_sites, PlaywrightRenderer(browser_path=BROWSER))
    assert gw.fetch(url, OWN, []).ok
    assert not any(host == "elsewhere.test" for host, _ in fixture_sites.requests)


@needs_browser
def test_rendering_a_page_that_stays_empty_is_not_readable(engine, clean, fixture_sites):
    url = portal(fixture_sites, "/* nothing */")
    page = gateway(engine, fixture_sites, PlaywrightRenderer(browser_path=BROWSER)).fetch(url, OWN, [])
    assert page.blocked == "not_readable:render" and not page.ok


def test_a_missing_browser_is_not_readable_and_keeps_a_flagged_snapshot(engine, clean, fixture_sites):
    url = portal(fixture_sites)
    SourceDomains(engine, "pai").sync(load_allowlist(os.path.join(os.path.dirname(__file__), "fixtures", "sources")))
    guard = SourceGuard(engine, "pai")
    gw = gateway(engine, fixture_sites, PlaywrightRenderer(browser_path="/no/such/browser"), sources=guard)
    page = gw.fetch(url, [], [], scope=Scope(region="north_region", family="university"))
    assert page.blocked == "not_readable:render"
    snap = guard.snapshots.get(page.snapshot_id)
    assert snap.flagged == "not_readable"
    assert guard.snapshots.latest(url) is None  # never the "last clean" snapshot
    with pytest.raises(RenderFailed):
        PlaywrightRenderer(browser_path="/no/such/browser").render(url, lambda u: None)


@needs_browser
def test_rendered_text_has_a_snapshot_marked_render(engine, clean, fixture_sites):
    url = portal(fixture_sites)
    SourceDomains(engine, "pai").sync(load_allowlist(os.path.join(os.path.dirname(__file__), "fixtures", "sources")))
    guard = SourceGuard(engine, "pai")
    page = gateway(engine, fixture_sites, PlaywrightRenderer(browser_path=BROWSER), sources=guard).fetch(url, OWN, [])
    assert page.ok
    with engine.connect() as conn:
        row = conn.execute(select(models.page_snapshots.c.read_method)).first()
    assert row.read_method == "render"
