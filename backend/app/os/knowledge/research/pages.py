"""The page gateway: the only way research reads the web (Slice 2 spec §4.3, parent §3.2 tool gateway).

Checks, in order: the URL is on an official domain, robots.txt allows it, the host was not asked within the
last `fetch_host_interval_s`, and the page is HTML or PDF of at most `page_max_bytes`. Every page, read or
refused, is kept in os_pages for `page_ttl_h`: that is both the cache and the audit log of what was read.

Transient failures (network errors, 429 and 5xx) raise TransientFetchError and are not cached: the research
workflow runs each fetch as a DBOS step, so retries happen only there (invariant 7). When the retries are
used up the workflow calls `record_failure`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert

from app.os import models
from app.os import clock as shared_clock
from app.os.knowledge.research.links import domain_of, rank_links
from app.os.knowledge.research.text import html_to_text, pdf_to_text
from app.os.knowledge.sources.integrity import is_tls_failure
from app.os.settings import OsSettings

if TYPE_CHECKING:  # P2-T3: the guard is optional; with none, the gateway behaves as before
    from app.os.knowledge.sources.allowlist import Scope
    from app.os.knowledge.sources.suspect import SourceGuard

USER_AGENT = "PAI-OS-research/1 (study-route research; respects robots.txt)"
P = models.pages
_NO_REQUEST = ("not_official", "robots")  # refused before any request: they do not count for the host interval


class TransientFetchError(Exception):
    """A failure worth retrying (network, 429, 5xx). Never cached."""


class _TlsFailure(Exception):
    """An invalid certificate or handshake, seen with a source guard: recorded and flagged, never retried."""


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str | None = None
    http_status: int | None = None
    text: str = ""
    links: tuple[tuple[str, str], ...] = ()
    blocked: str | None = None  # not_official | robots | http_<n> | too_big | unsupported:<type> | ... | error:<x>
    #                             P2-T3 adds: suspect_domain | integrity:<code> | tls_invalid
    fetched_at: datetime | None = None
    from_cache: bool = field(default=False, compare=False)
    snapshot_id: int | None = field(default=None, compare=False)  # the os_page_snapshots row of this read (guard on)

    @property
    def ok(self) -> bool:
        return self.blocked is None and bool(self.text)


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


class PageGateway:
    def __init__(self, engine: Engine, tenant_id: str, settings: OsSettings, client: httpx.Client | None = None,
                 clock: Callable[[], datetime] = shared_clock.now, sleep: Callable[[float], None] = _sleep,
                 sources: "SourceGuard | None" = None) -> None:
        self.engine, self.tenant_id, self.settings = engine, tenant_id, settings
        self.sources = sources
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                                             timeout=20.0)
        self.clock, self.sleep = clock, sleep
        self._robots: dict[str, RobotFileParser] = {}

    # --- cache / audit ------------------------------------------------------------------------------

    def _cached(self, url: str) -> Page | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(P).where(P.c.tenant_id == self.tenant_id, P.c.url == url)).first()
        if row is None or self.clock() - row.fetched_at > timedelta(hours=self.settings.page_ttl_h):
            return None
        return Page(url=row.url, final_url=row.final_url, http_status=row.http_status, text=row.text,
                    links=tuple(tuple(x) for x in row.links), blocked=row.blocked, fetched_at=row.fetched_at,
                    from_cache=True)

    def _store(self, conn, page: Page) -> Page:
        values = {"final_url": page.final_url, "http_status": page.http_status, "text": page.text,
                  "links": [list(x) for x in page.links], "blocked": page.blocked, "fetched_at": page.fetched_at}
        conn.execute(insert(P).values(tenant_id=self.tenant_id, url=page.url, **values)
                     .on_conflict_do_update(constraint="uq_os_pages_url", set_=values))
        return page

    def _refuse(self, url: str, reason: str) -> Page:
        with self.engine.begin() as conn:
            return self._store(conn, Page(url=url, blocked=reason, fetched_at=self.clock()))

    def record_failure(self, url: str, reason: str) -> Page:
        """Called when the step retries for a transient failure are used up."""
        return self._refuse(url, f"error:{reason}")

    # --- checks -------------------------------------------------------------------------------------

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.client.get(origin + "/robots.txt")
            except httpx.TransportError as e:
                if self.sources is not None and is_tls_failure(e):
                    raise _TlsFailure(type(e).__name__) from e
                raise TransientFetchError(f"robots.txt: {type(e).__name__}") from e
            if r.status_code in (401, 403) or r.status_code >= 500:
                rp.disallow_all = True  # RFC 9309: unreachable or forbidden robots.txt means stay out
            elif r.status_code >= 400:
                rp.allow_all = True  # no robots.txt
            else:
                rp.parse(r.text.splitlines())
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def _wait_for_host(self, conn, host: str) -> None:
        """Holds a per-host advisory lock for the transaction and waits out the minimum interval."""
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"os.fetch:{host}"))))
        last = conn.execute(select(func.max(P.c.fetched_at)).where(
            func.split_part(P.c.url, "/", 3) == host,
            (P.c.blocked.is_(None)) | (P.c.blocked.not_in(_NO_REQUEST)),
        )).scalar()
        if last is not None:
            wait = self.settings.fetch_host_interval_s - (self.clock() - last).total_seconds()
            if wait > 0:
                self.sleep(wait)

    def _download(self, url: str) -> tuple[httpx.Response, bytes | None]:
        """The body, or None when it is over the size limit."""
        limit = self.settings.page_max_bytes
        with self.client.stream("GET", url) as r:
            size = r.headers.get("content-length")
            if size and size.isdigit() and int(size) > limit:
                return r, None
            body = bytearray()
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > limit:
                    return r, None
            return r, bytes(body)

    # --- public -------------------------------------------------------------------------------------

    def fetch(self, url: str, own_domains: Sequence[str], shared_domains: Sequence[str],
              scope: "Scope | None" = None) -> Page:
        """`scope` (region and family, or route) is used only with a source guard: a domain on the reviewed
        allow-list for that scope is official too, besides the lists the caller passes."""
        guard = self.sources
        if guard is not None and guard.is_suspect(url):  # before the cache: nothing is taken from a suspect domain
            return Page(url=url, blocked="suspect_domain", fetched_at=self.clock())  # not cached: the state can change
        if guard is not None and urlsplit(url).scheme.lower() != "https":  # review I6: https only with the guard
            return Page(url=url, blocked="insecure_scheme", fetched_at=self.clock())
        cached = self._cached(url)
        if cached is not None and not (guard is not None and (cached.blocked or "").startswith(
                ("integrity:", "tls_", "suspect_domain"))):
            return cached  # (a cached integrity block is read again once the domain is active: only approvers get it so)
        official = set(own_domains) | set(shared_domains)
        allowed = self._allowed(official, scope)
        if not allowed(url):
            return self._refuse(url, "not_official")
        try:
            robots_ok = self._robots_allows(url)
        except _TlsFailure as e:
            guard.flag(url, "tls_invalid", str(e))
            return self._refuse(url, "tls_invalid")
        if not robots_ok:
            return self._refuse(url, "robots")
        host = urlsplit(url).netloc.lower()
        flags: list[tuple] = []  # the suspect flow runs after the page transaction, never under its lock (review M3)
        with self.engine.begin() as conn:  # the advisory lock is held until this page is stored
            self._wait_for_host(conn, host)
            try:
                r, body = self._download(url)
            except httpx.TransportError as e:
                if guard is None or not is_tls_failure(e):
                    raise TransientFetchError(f"{type(e).__name__}") from e
                # recorded and flagged, not retried or ignored (R-71)
                flags.append((url, "tls_invalid", f"{type(e).__name__}", None))
                page = self._store(conn, Page(url=url, blocked="tls_invalid", fetched_at=self.clock()))
            else:
                page = self._store(conn, self._page(url, r, body, official, allowed, flags))
        for args in flags:
            guard.flag(*args)
        return page

    def _allowed(self, official: set[str], scope: "Scope | None") -> Callable[[str], bool]:
        guard = self.sources
        return lambda u: domain_of(u) in official or (guard is not None and guard.is_listed(u, scope))

    def _page(self, url: str, r: httpx.Response, body: bytes | None, official: set[str],
              allowed: Callable[[str], bool] | None = None, flags: list | None = None) -> Page:
        base = {"url": url, "final_url": str(r.url), "http_status": r.status_code, "fetched_at": self.clock()}
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"http_{r.status_code}")
        if r.status_code >= 400:
            return Page(**base, blocked=f"http_{r.status_code}")
        if self.sources is not None:  # the final URL after redirects is checked like the first (review I1, I6)
            if self.sources.is_suspect(str(r.url)):
                return Page(**base, blocked="suspect_domain")
            if r.url.scheme.lower() != "https":
                return Page(**base, blocked="insecure_scheme")
        if not (allowed(str(r.url)) if allowed else domain_of(str(r.url)) in official):
            return Page(**base, blocked="redirect_not_official")
        if body is None:
            return Page(**base, blocked="too_big")
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "application/pdf" or (not ctype and url.lower().endswith(".pdf")):
            try:
                text = pdf_to_text(body)
            except Exception:  # a broken PDF is a page we cannot read, not a retry
                return Page(**base, blocked="unreadable_pdf")
            return self._inspected(Page(**base, text=text), ctype or "application/pdf", allowed, official, body,
                                   flags=flags)
        if "html" in ctype or not ctype:
            text, links = html_to_text(body.decode(r.encoding or "utf-8", errors="replace"), str(r.url))
            return self._inspected(Page(**base, text=text, links=tuple(links)), ctype or "text/html", allowed,
                                   official, flags=flags)
        return Page(**base, blocked=f"unsupported:{ctype}")

    def _inspected(self, page: Page, ctype: str, allowed: Callable[[str], bool] | None, official: set[str],
                   original: bytes | None = None, *, flags: list | None = None) -> Page:
        """With a source guard: integrity checks and the snapshot. A failed check blocks the page (its text is
        kept only in the snapshot) and marks the domain suspect (after the page transaction when `flags` is given)."""
        guard = self.sources
        if guard is None:
            return page
        is_official = allowed or (lambda u: domain_of(u) in official)
        got = guard.inspect(page.url, page.text, page.links, content_type=ctype, fetched_at=page.fetched_at,
                            is_official=is_official, original=original, original_type=ctype if original else None,
                            flag=flags is None)
        if got.findings and flags is not None:
            from app.os.knowledge.sources.suspect import describe
            flags.append((page.url, got.findings[0].code, describe(got.findings), got.snapshot_id))
        if got.findings:
            return replace(page, text="", links=(), blocked=f"integrity:{got.findings[0].code}",
                           snapshot_id=got.snapshot_id)
        return replace(page, snapshot_id=got.snapshot_id)

    def fetch_or_record(self, url: str, own_domains: Sequence[str], shared_domains: Sequence[str],
                        scope: "Scope | None" = None) -> Page:
        """For callers outside a DBOS step: one try, and a transient failure is recorded as a blocked page."""
        try:
            return self.fetch(url, own_domains, shared_domains, scope)
        except TransientFetchError as e:
            return self.record_failure(url, str(e))

    def collect(self, programme, profile, fetch: Callable[[str], Page] | None = None) -> list[Page]:
        """The programme's start pages, then up to 5 ranked links on its own domains (spec §4.3)."""
        own, shared = programme.official_domains, profile.official_sources
        get = fetch or (lambda u: self.fetch_or_record(u, own, shared))
        pages = [get(u) for u in programme.start_urls]
        seen = set(programme.start_urls) | {p.final_url for p in pages if p.final_url}
        pages += [get(u) for u in rank_links([p for p in pages if p.ok], own, profile.link_keywords, seen)]
        return pages
