"""FU-9 (T22): a cached page is never served to a scope it is not listed for (P2 spec §4.2, P2-D10; master R-71, R-24).

`os_pages` is keyed by URL only. With a source guard the allow-list for the asked scope is checked before the cache,
and a `not_official` refusal is not stored, so it cannot block a scope that lists the host. Fictional `.test` sites.
"""

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.sources.allowlist import Scope
from tests.os.test_p2_sources_gateway import ALPHA, NORTH, build

pytestmark = pytest.mark.req("R-71", "R-24")
SOUTH = Scope(region="south_region", family="university")  # alpha-university.test is listed for NORTH only
NOTICE = "/admissions/notice"


def stored(engine, url):
    with engine.connect() as conn:
        return conn.execute(select(models.pages.c.blocked, models.pages.c.text)
                            .where(models.pages.c.url == url)).first()


def test_a_page_cached_under_one_scope_is_refused_under_an_unlisted_scope(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    url = fixture_sites.url(ALPHA, NOTICE)
    first = gw.fetch(url, [], [], NORTH)
    assert first.ok and not first.from_cache

    other = gw.fetch(url, [], [], SOUTH)
    assert other.blocked == "not_official" and not other.ok and other.text == "" and not other.from_cache
    assert gw.fetch(url, [], []).blocked == "not_official"  # no scope at all: refused too

    row = stored(engine, url)  # the refusal did not overwrite the page read for NORTH
    assert row.blocked is None and row.text == first.text
    again = gw.fetch(url, [], [], NORTH)
    assert again.ok and again.from_cache and again.text == first.text


def test_a_refusal_under_an_unlisted_scope_does_not_block_a_listed_scope(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    url = fixture_sites.url(ALPHA, NOTICE)
    assert gw.fetch(url, [], [], SOUTH).blocked == "not_official"
    assert stored(engine, url) is None  # a scope-dependent refusal is not cached under the URL
    assert (ALPHA, NOTICE) not in fixture_sites.requests  # refused before any request, as before

    page = gw.fetch(url, [], [], NORTH)
    assert page.ok and not page.from_cache and (ALPHA, NOTICE) in fixture_sites.requests


def test_a_not_official_row_from_before_is_read_again_for_a_listed_scope(engine, clean, fixture_sites):
    url = fixture_sites.url(ALPHA, NOTICE)
    plain, _, _ = build(engine, fixture_sites, guard=False)
    assert plain.fetch(url, [], []).blocked == "not_official"  # without a guard the refusal is cached, as before
    assert stored(engine, url).blocked == "not_official"

    gw, _, _ = build(engine, fixture_sites)
    page = gw.fetch(url, [], [], NORTH)
    assert page.ok and not page.from_cache


def test_a_cached_redirect_is_judged_for_the_asked_scope(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    url = fixture_sites.url(ALPHA, "/moved")  # redirects to elsewhere.test, which no allow-list has
    assert gw.fetch(url, ["elsewhere.test"], [], NORTH).ok  # the caller's own list allows the target

    page = gw.fetch(url, [], [], NORTH)  # the cached page, asked without that list
    assert page.blocked == "redirect_not_official" and page.text == "" and not page.ok
    assert stored(engine, url).blocked is None  # not stored: the row stays valid for the caller that lists the target


def test_a_cached_redirect_refusal_does_not_block_a_caller_that_allows_the_target(engine, clean, fixture_sites):
    gw, _, _ = build(engine, fixture_sites)
    url = fixture_sites.url(ALPHA, "/moved")
    first = gw.fetch(url, [], [], NORTH)
    assert first.blocked == "redirect_not_official"
    again = gw.fetch(url, [], [], NORTH)
    assert again.blocked == "redirect_not_official" and again.from_cache  # still refused for this caller, no request

    page = gw.fetch(url, ["elsewhere.test"], [], NORTH)
    assert page.ok and not page.from_cache


def test_without_a_guard_the_cache_works_as_before(engine, clean, fixture_sites):
    """Regression guard for task item 3: passes before and after FU-9, by design."""
    gw, _, _ = build(engine, fixture_sites, guard=False)
    url = fixture_sites.url(ALPHA, NOTICE)
    first = gw.fetch(url, ["alpha-university.test"], [])
    assert first.ok and not first.from_cache
    other = gw.fetch(url, [], [], SOUTH)  # no guard: the cache is read first, whatever the lists or scope
    assert other.ok and other.from_cache and other.text == first.text

    refused = fixture_sites.url(ALPHA, "/admissions/portal")
    assert gw.fetch(refused, [], []).blocked == "not_official"
    assert stored(engine, refused).blocked == "not_official"  # cached under the URL, as before
    later = gw.fetch(refused, ["alpha-university.test"], [])
    assert later.blocked == "not_official" and later.from_cache
