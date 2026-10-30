"""Slice 2 Task 3: the page gateway, text and links (spec §4.3)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.os import models
from app.os.knowledge.research.links import rank_links, registrable
from app.os.knowledge.research.pages import Page, PageGateway, TransientFetchError
from app.os.knowledge.research.text import html_to_text, normalise, pdf_to_text
from app.os.settings import load_settings

OWN = ("uni-x.de",)
SHARED = ("hub.org",)
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
HTML = ("<html><body><nav><a href='/login'>Login</a></nav><h1>MSc Data</h1><p>Deadline: 15 July</p>"
        "<a href='/apply/deadlines'>Application deadlines</a> <a href='https://other.org/apply'>Apply elsewhere</a>"
        "<script>var x = 1;</script></body></html>")


def minimal_pdf(text: str) -> bytes:
    """A one-page PDF with `text`, built by hand (no extra dependency)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


class Site:
    """A fake web: path -> (status, content type, body). Counts requests per URL."""

    def __init__(self, pages: dict, robots: tuple[int, str] = (404, "")) -> None:
        self.pages, self.robots, self.hits = pages, robots, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(self.robots[0], text=self.robots[1])
        if url not in self.pages:
            return httpx.Response(404)
        item = self.pages[url]
        if isinstance(item, Exception):
            raise item
        status, ctype, body = item
        if status in (301, 302):
            return httpx.Response(status, headers={"location": body})
        return httpx.Response(status, headers={"content-type": ctype}, content=body)


class Clock:
    def __init__(self) -> None:
        self.now, self.slept = T0, []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += timedelta(seconds=seconds)


def gateway(engine, site: Site, clock: Clock | None = None, **env) -> PageGateway:
    clock = clock or Clock()
    settings = load_settings({"DATABASE_URL": "x", **env})
    client = httpx.Client(transport=httpx.MockTransport(site), follow_redirects=True)
    return PageGateway(engine, "pai", settings, client=client, clock=clock, sleep=clock.sleep)


def page_rows(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.pages)).scalar_one()


# --- text and links (no database) ---------------------------------------------------------------------


def test_html_text_skips_scripts_and_collects_links():
    text, links = html_to_text(HTML, "https://www.uni-x.de/msc")
    assert "Deadline: 15 July" in text.splitlines()
    assert "var x" not in text
    assert ("https://www.uni-x.de/apply/deadlines", "Application deadlines") in links


def test_pdf_text():
    assert "Deadline 15 July" in pdf_to_text(minimal_pdf("Deadline 15 July"))


def test_normalise_maps_spaces_dashes_quotes_and_case():
    assert normalise("1 April – 15 July") == "1 april - 15 july"
    assert normalise("a\x00a0b") == "a b"  # a model's rendering of a non-breaking space (Spike 1)
    assert normalise("“Master’s”") == "\"master's\""


def test_registrable():
    assert registrable("www2.daad.de") == "daad.de" and registrable("WWW.Uni-X.de.") == "uni-x.de"


@dataclass
class P:
    links: list


def test_rank_links_own_domains_only():
    pages = [P(links=[
        ("https://www.uni-x.de/apply/deadlines", "Application deadlines"),
        ("https://www.uni-x.de/msc/admission", "Admission requirements"),
        ("https://hub.org/apply", "Apply"),  # shared hub: not followed
        ("https://other.org/admission", "Admission"),  # not official
        ("https://www.uni-x.de/login?next=apply", "Login"),  # portal
        ("https://www.uni-x.de/r?url=https%3A%2F%2Fevil.org", "Apply"),  # wraps another URL
        ("https://www.uni-x.de/about", "About us"),  # no keyword
        ("https://www.uni-x.de/seen-apply", "Apply"),  # already read
    ])]
    got = rank_links(pages, OWN, ["apply", "application", "admission", "deadline", "requirement"],
                     seen={"https://www.uni-x.de/seen-apply"})
    assert got == ["https://www.uni-x.de/apply/deadlines", "https://www.uni-x.de/msc/admission"]


def test_rank_links_limit_and_order_is_deterministic():
    pages = [P(links=[(f"https://uni-x.de/apply/{i}", "apply") for i in (3, 1, 2, 9, 7, 5)])]
    assert rank_links(pages, OWN, ["apply"], set(), limit=3) == [
        "https://uni-x.de/apply/1", "https://uni-x.de/apply/2", "https://uni-x.de/apply/3"]


# --- gateway (Postgres) ---------------------------------------------------------------------------------


def test_not_official_not_fetched(engine, clean):
    site = Site({"https://other.org/x": (200, "text/html", b"<p>x</p>")})
    page = gateway(engine, site).fetch("https://other.org/x", OWN, SHARED)
    assert page.blocked == "not_official" and site.hits == [] and page_rows(engine) == 1


def test_shared_domain_is_official(engine, clean):
    site = Site({"https://www.hub.org/p": (200, "text/html", b"<p>Fees: none</p>")})
    assert gateway(engine, site).fetch("https://www.hub.org/p", OWN, SHARED).ok


def test_robots_disallow(engine, clean):
    site = Site({"https://www.uni-x.de/private/p": (200, "text/html", b"<p>x</p>")},
                robots=(200, "User-agent: *\nDisallow: /private/"))
    page = gateway(engine, site).fetch("https://www.uni-x.de/private/p", OWN, SHARED)
    assert page.blocked == "robots" and site.hits == ["https://www.uni-x.de/robots.txt"]


@pytest.mark.parametrize("status", [401, 403, 503])
def test_robots_forbidden_or_unreachable_disallows_all(engine, clean, status):
    site = Site({"https://www.uni-x.de/p": (200, "text/html", b"<p>x</p>")}, robots=(status, ""))
    assert gateway(engine, site).fetch("https://www.uni-x.de/p", OWN, SHARED).blocked == "robots"


def test_missing_robots_allows(engine, clean):
    site = Site({"https://www.uni-x.de/p": (200, "text/html", b"<p>Deadline</p>")}, robots=(404, ""))
    page = gateway(engine, site).fetch("https://www.uni-x.de/p", OWN, SHARED)
    assert page.ok and page.text == "Deadline" and page.http_status == 200


def test_host_interval_respected(engine, clean):
    site = Site({f"https://www.uni-x.de/{n}": (200, "text/html", b"<p>x</p>") for n in "abc"} |
                {"https://www.hub.org/d": (200, "text/html", b"<p>y</p>")})
    clock = Clock()
    gw = gateway(engine, site, clock, OS_FETCH_HOST_INTERVAL_S="2")
    gw.fetch("https://www.uni-x.de/a", OWN, SHARED)
    gw.fetch("https://www.uni-x.de/b", OWN, SHARED)  # same host at once: waits 2 s
    clock.now += timedelta(seconds=5)
    gw.fetch("https://www.uni-x.de/c", OWN, SHARED)  # interval already passed: no wait
    gw.fetch("https://www.hub.org/d", OWN, SHARED)  # another host: no wait
    assert clock.slept == [2.0]


def test_refused_pages_do_not_count_for_the_interval(engine, clean):
    site = Site({"https://www.uni-x.de/a": (200, "text/html", b"<p>x</p>")},
                robots=(200, "User-agent: *\nDisallow: /private/"))
    clock = Clock()
    gw = gateway(engine, site, clock)
    gw.fetch("https://www.uni-x.de/private/z", OWN, SHARED)  # refused by robots: no request made
    gw.fetch("https://www.uni-x.de/a", OWN, SHARED)
    assert clock.slept == []


def test_too_big_refused(engine, clean):
    site = Site({"https://www.uni-x.de/big": (200, "text/html", b"<p>" + b"x" * 2000 + b"</p>")})
    page = gateway(engine, site, OS_PAGE_MAX_BYTES="1000").fetch("https://www.uni-x.de/big", OWN, SHARED)
    assert page.blocked == "too_big" and page.text == ""


def test_pdf_page(engine, clean):
    site = Site({"https://www.uni-x.de/h.pdf": (200, "application/pdf", minimal_pdf("IELTS 6.5"))})
    page = gateway(engine, site).fetch("https://www.uni-x.de/h.pdf", OWN, SHARED)
    assert page.ok and "IELTS 6.5" in page.text


def test_unsupported_type_refused(engine, clean):
    site = Site({"https://www.uni-x.de/i.png": (200, "image/png", b"\x89PNG")})
    assert gateway(engine, site).fetch("https://www.uni-x.de/i.png", OWN, SHARED).blocked == "unsupported:image/png"


def test_http_404_cached_as_blocked(engine, clean):
    site = Site({})
    page = gateway(engine, site).fetch("https://www.uni-x.de/gone", OWN, SHARED)
    assert page.blocked == "http_404" and page_rows(engine) == 1


def test_redirect_off_official_domain_refused(engine, clean):
    site = Site({"https://www.uni-x.de/r": (302, "", "https://other.org/landing"),
                 "https://other.org/landing": (200, "text/html", b"<p>x</p>")})
    page = gateway(engine, site).fetch("https://www.uni-x.de/r", OWN, SHARED)
    assert page.blocked == "redirect_not_official" and page.text == ""


@pytest.mark.parametrize("failure", [(503, "text/html", b""), (429, "text/html", b""),
                                     httpx.ConnectTimeout("slow")])
def test_transient_failure_raises_and_is_not_cached(engine, clean, failure):
    site = Site({"https://www.uni-x.de/p": failure})
    with pytest.raises(TransientFetchError):
        gateway(engine, site).fetch("https://www.uni-x.de/p", OWN, SHARED)
    assert page_rows(engine) == 0


def test_record_failure_after_retries(engine, clean):
    site = Site({"https://www.uni-x.de/p": httpx.ConnectError("down")})
    page = gateway(engine, site).fetch_or_record("https://www.uni-x.de/p", OWN, SHARED)
    assert page.blocked == "error:ConnectError" and page_rows(engine) == 1


def test_cache_ttl_and_audit_row(engine, clean):
    site = Site({"https://www.uni-x.de/p": (200, "text/html", b"<p>v1</p>")})
    clock = Clock()
    gw = gateway(engine, site, clock, OS_PAGE_TTL_H="24")
    first = gw.fetch("https://www.uni-x.de/p", OWN, SHARED)
    clock.now += timedelta(hours=23)
    again = gw.fetch("https://www.uni-x.de/p", OWN, SHARED)
    assert again.from_cache and again.text == "v1" and site.hits.count("https://www.uni-x.de/p") == 1
    site.pages["https://www.uni-x.de/p"] = (200, "text/html", b"<p>v2</p>")
    clock.now += timedelta(hours=2)
    fresh = gw.fetch("https://www.uni-x.de/p", OWN, SHARED)
    assert not fresh.from_cache and fresh.text == "v2" and site.hits.count("https://www.uni-x.de/p") == 2
    with engine.connect() as conn:
        row = conn.execute(select(models.pages)).one()
    assert (row.url, row.text, row.http_status, row.fetched_at) == ("https://www.uni-x.de/p", "v2", 200, fresh.fetched_at)
    assert first.fetched_at < fresh.fetched_at


def test_cache_is_per_tenant(engine, clean):
    site = Site({"https://www.uni-x.de/p": (200, "text/html", b"<p>x</p>")})
    gw = gateway(engine, site)
    gw.fetch("https://www.uni-x.de/p", OWN, SHARED)
    other = PageGateway(engine, "other", gw.settings, client=gw.client, clock=gw.clock, sleep=gw.sleep)
    assert not other.fetch("https://www.uni-x.de/p", OWN, SHARED).from_cache


@dataclass
class Prog:
    start_urls: tuple
    official_domains: tuple


@dataclass
class Prof:
    official_sources: list
    link_keywords: list


def test_collect_start_pages_then_ranked_links(engine, clean):
    site = Site({
        "https://www.hub.org/detail/1": (200, "text/html",
                                          b"<a href='https://www.uni-x.de/msc'>Programme page</a>"),
        "https://www.uni-x.de/msc": (200, "text/html", HTML.encode()),
        "https://www.uni-x.de/apply/deadlines": (200, "text/html", b"<p>Winter: 15 July</p>"),
    })
    prog = Prog(start_urls=("https://www.hub.org/detail/1", "https://www.uni-x.de/msc"), official_domains=OWN)
    pages = gateway(engine, site).collect(prog, Prof(official_sources=list(SHARED), link_keywords=["deadline"]))
    assert [p.url for p in pages] == ["https://www.hub.org/detail/1", "https://www.uni-x.de/msc",
                                      "https://www.uni-x.de/apply/deadlines"]
    assert all(isinstance(p, Page) and p.ok for p in pages)


def test_collect_uses_the_given_fetch(engine, clean):
    calls = []
    prog = Prog(start_urls=("https://www.uni-x.de/a",), official_domains=OWN)
    gateway(engine, Site({})).collect(prog, Prof(official_sources=[], link_keywords=[]),
                                      fetch=lambda u: calls.append(u) or Page(url=u, blocked="http_404"))
    assert calls == ["https://www.uni-x.de/a"]


def test_too_big_refused_without_content_length(engine, clean):
    """A chunked body has no Content-Length: the size is checked while streaming."""
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=iter([b"x" * 600, b"x" * 600]))

    gw = gateway(engine, Site({}), OS_PAGE_MAX_BYTES="1000")
    gw.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert gw.fetch("https://www.uni-x.de/stream", OWN, SHARED).blocked == "too_big"
