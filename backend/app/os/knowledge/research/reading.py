"""How the gateway reads what a plain fetch cannot: JavaScript shells (render) and scans (OCR) (P2-T4).

Kept out of `pages.py` so the gateway only has three small hooks. A failure is never silent: it becomes a page blocked
`not_readable:render` / `not_readable:ocr`, with a flagged snapshot (and the original file) for the checker who collects
the value by hand (R-72).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.os.knowledge.research.readability import annotate_snapshot
from app.os.knowledge.research.render import (
    RenderFailed,
    SubLimits,
    looks_like_js_shell,
)
from app.os.knowledge.research.scan import ScanFailed, scan_document
from app.os.knowledge.research.text import detect_language, html_to_text

if TYPE_CHECKING:
    import httpx

    from app.os.knowledge.research.pages import Page, PageGateway

__all__ = ["looks_like_js_shell", "rendered", "scanned"]


def _fail(gw: PageGateway, page: Page, reason: str, ctype: str, original: bytes | None) -> Page:
    """A page that could not be read: blocked, and (with a source guard) kept as a flagged snapshot."""
    blocked = replace(page, text="", links=(), language=None, blocked=f"not_readable:{reason}")
    guard = gw.sources
    if guard is None:
        return blocked
    keep = original if original is not None and len(original) <= guard.snapshots.max_bytes else None
    snap = guard.snapshots.save(page.url, page.text or "", content_type=ctype, flagged="not_readable",
                                fetched_at=page.fetched_at, original=keep, original_type=ctype if keep else None)
    return replace(blocked, snapshot_id=snap.id)


def rendered(gw: PageGateway, page: Page, r: httpx.Response, html: str, ctype: str, allowed, official,
             flags: list | None = None) -> Page:
    """The page's DOM after JavaScript ran (R-74). Falls back to `not_readable:render` when rendering fails or the
    rendered page has no text."""
    final = str(r.url)

    def fetch(url: str, limits: SubLimits):
        """One sub-request of the render: the same rules as a page of its own (allow-list, robots.txt, the host
        interval), the time left, and a byte limit while streaming. A redirect is not followed here: the browser asks
        again for the new URL, which is checked in turn."""
        if limits.time_left_s <= 0 or not allowed(url):
            return None
        try:
            if not gw._robots_allows(url):
                return None
        except Exception:  # noqa: BLE001  (robots.txt unreachable: stay out)
            return None
        gw.pace(urlsplit(url).netloc.lower(), limits.time_left_s)  # the gateway's own per-host clock
        limit = min(limits.max_bytes, gw.settings.page_max_bytes)
        try:
            with gw.client.stream("GET", url, follow_redirects=False) as resp:
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > limit:
                    return None
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > limit:
                        return None
                return resp.status_code, dict(resp.headers), bytes(body)
        except Exception:  # noqa: BLE001  (a failed sub-request is a refused sub-request)
            return None

    try:
        out = gw.renderer.render(final, fetch)
    except RenderFailed:
        return _fail(gw, page, "render", ctype, None)
    if not allowed(out.final_url):
        return _fail(gw, page, "render", ctype, None)
    text, links = html_to_text(out.html, out.final_url)
    if not text.strip():
        return _fail(gw, page, "render", ctype, None)
    out_page = replace(page, text=text, links=tuple(links), read_method="render", language=detect_language(text))
    return _annotated(gw, gw._inspected(out_page, ctype, allowed, official, flags=flags), "render")


def scanned(gw: PageGateway, page: Page, data: bytes, ctype: str, allowed, official, flags: list | None = None) -> Page:
    """An image or an image-only PDF through the scanner (R-29): `read_method: ocr`, original kept."""
    try:
        got = scan_document(gw.scanner, data, ctype, max_pages=gw.settings.scan_max_pages,
                            max_pixels=gw.settings.scan_max_pixels)
    except ScanFailed:
        return _fail(gw, page, "ocr", ctype, data)
    out_page = replace(page, text=got.text, links=(), read_method="ocr", language=detect_language(got.text))
    return _annotated(gw, gw._inspected(out_page, ctype, allowed, official, data, flags=flags), "ocr")


def _annotated(gw: PageGateway, page: Page, method: str) -> Page:
    if gw.sources is not None and not page.blocked:
        annotate_snapshot(gw.engine, gw.tenant_id, page.snapshot_id, read_method=method, language=page.language)
    return page


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""
