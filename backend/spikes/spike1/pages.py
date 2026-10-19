"""Reading official pages: robots.txt, an on-disk cache, HTML/PDF to text, and link ranking.

Design SP1-D4 and SP1-D5. No AI here. A page is fetched once per cache directory, so both readings
see the same text and a re-run costs nothing to fetch.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pypdf import PdfReader

USER_AGENT = "PAI-OS-research-spike/1 (study-route research; respects robots.txt)"
PAGE_CHARS = 15_000  # per page sent to the model
MAX_LINKED = 5  # SP1-D5: links followed beyond the start URLs

# DAAD runs myGUIDE; uni-assist runs the application service (parent §3.2 official sources).
SHARED_OFFICIAL = ("uni-assist.de", "daad.de", "myguide.de")

_BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "dt", "dd", "table"}
_SKIP = {"script", "style", "noscript", "svg", "template"}
_LINK_WORDS = ("apply", "application", "admission", "deadline", "requirement", "bewerbung", "zulassung",
               "fee", "language", "international", "faq", "how-to", "dates", "tuition", "semester",
               "master", "programme", "program", "course", "studiengang")
_JUNK = ("qisserver", ".faces", "login", "/sso", "accessibility", "barrier", "doctora", "refugee", "exchange",
         "mailto:", "/news", "/events")


class _TextAndLinks(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.links, self._skip, self._href, self._anchor = base, [], [], 0, None, []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._href, self._anchor = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._href:
            url = urldefrag(urljoin(self.base, self._href))[0]
            if url.startswith(("http://", "https://")):
                self.links.append((url, " ".join(self._anchor).strip()))
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)
            if self._href is not None:
                self._anchor.append(data.strip())


def normalise(text: str) -> str:
    """Whitespace collapsed and case folded; quotes are matched in this form (SP1-D7 b)."""
    text = text.replace(" ", " ").replace("–", "-").replace("—", "-")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


def html_to_text(html: str, base: str) -> tuple[str, list[tuple[str, str]]]:
    p = _TextAndLinks(base)
    p.feed(html)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line), p.links


def pdf_to_text(data: bytes) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)


def registrable(host: str) -> str:
    """'www2.daad.de' -> 'daad.de'. Good enough for the German university domains in the shortlist."""
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def is_official(url: str, domains: tuple[str, ...]) -> bool:
    return registrable(urlsplit(url).hostname or "") in set(domains) | set(SHARED_OFFICIAL)


@dataclass
class Page:
    url: str
    final_url: str = ""
    status: int = 0
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    blocked: str | None = None  # robots | http_<status> | error:<type> | unsupported:<type>
    fetched_at: str = ""

    @property
    def ok(self) -> bool:
        return self.blocked is None and bool(self.text)


class Fetcher:
    def __init__(self, cache_dir: Path, client: httpx.Client | None = None) -> None:
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20.0)
        self._robots: dict[str, RobotFileParser | None] = {}

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                r = self.client.get(origin + "/robots.txt")
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp = None  # no robots.txt: everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> Page:
        path = self._cache_path(url)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["links"] = [tuple(x) for x in data["links"]]
            return Page(**data)
        page = Page(url=url, fetched_at=datetime.now(UTC).isoformat(timespec="seconds"))
        if not self._allowed(url):
            page.blocked = "robots"
        else:
            try:
                r = self.client.get(url)
                page.status, page.final_url = r.status_code, str(r.url)
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code >= 400:
                    page.blocked = f"http_{r.status_code}"
                elif ctype == "application/pdf" or url.lower().endswith(".pdf"):
                    page.text = pdf_to_text(r.content)
                elif "html" in ctype or not ctype:
                    page.text, page.links = html_to_text(r.text, page.final_url)
                else:
                    page.blocked = f"unsupported:{ctype}"
            except (httpx.HTTPError, ValueError) as e:  # one try only: no retry code (invariant 7)
                page.blocked = f"error:{type(e).__name__}"
        path.write_text(json.dumps(asdict(page), ensure_ascii=False), encoding="utf-8")
        return page


def rank_links(pages: list[Page], domains: tuple[str, ...], seen: set[str], limit: int = MAX_LINKED) -> list[str]:
    """Links on the university's own domains whose URL or anchor names an application topic, best first.

    Shared hubs (DAAD and uni-assist general pages) are not followed: they hold no programme facts and
    took most link slots in the dry run. Login portals and links that carry another URL are skipped.
    """
    own = set(domains)
    scores: dict[str, int] = {}
    for page in pages:
        for url, anchor in page.links:
            low = url.lower()
            if (url in seen or registrable(urlsplit(url).hostname or "") not in own
                    or any(j in low for j in _JUNK) or "url=" in low):
                continue
            hay = (url + " " + anchor).lower()
            score = sum(w in hay for w in _LINK_WORDS)
            if score:
                scores[url] = max(scores.get(url, 0), score)
    return [u for u, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]


def collect(fetcher: Fetcher, start_urls: list[str], domains: tuple[str, ...]) -> list[Page]:
    """The start pages, then up to MAX_LINKED ranked links from them."""
    pages = [fetcher.get(u) for u in start_urls]
    seen = set(start_urls) | {p.final_url for p in pages if p.final_url}
    pages += [fetcher.get(u) for u in rank_links([p for p in pages if p.ok], domains, seen)]
    return pages
