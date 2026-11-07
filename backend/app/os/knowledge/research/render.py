"""Headless reading for JavaScript pages (P2 spec §4.3, P2-D12; R-74).

When a fetched page is a JavaScript shell (little visible text, scripts present), the gateway renders it with
Playwright and reads the resulting DOM (`read_method: render`). The browser has NO network path of its own: it is
launched with a dead proxy, and every request it makes (page, scripts, XHR, redirects) is intercepted and answered by
the gateway's own HTTP client, only for GET and only for URLs the allow-list accepts. This is the egress rule of
`app/browser/egress.py` reached from the other side (no Counsellor code is imported: Tach). Service workers are blocked.
"""

from __future__ import annotations

import glob
import os
from collections.abc import Callable
from dataclasses import dataclass

# What a request may be answered with: status, headers, body. None refuses the request.
Fetched = tuple[int, dict[str, str], bytes]
_DROP = {"content-encoding", "content-length", "transfer-encoding", "connection"}  # the client already decoded the body


class RenderFailed(Exception):
    """The page could not be rendered (no browser, timeout, navigation refused or failed)."""


@dataclass(frozen=True)
class Rendered:
    html: str
    final_url: str


def looks_like_js_shell(html: str, visible_text: str, max_chars: int) -> bool:
    """A little visible text (thresholds in settings) and scripts in the page: the content is built by JavaScript."""
    return len(visible_text.strip()) < max_chars and "<script" in html.lower()


class PlaywrightRenderer:
    name = "playwright"

    def __init__(self, *, timeout_s: float = 20.0, browser_path: str | None = None, user_agent: str | None = None) -> None:
        self.timeout_s, self.browser_path, self.user_agent = timeout_s, browser_path, user_agent

    def _executable(self) -> str | None:
        path = self.browser_path or os.environ.get("OS_RENDER_BROWSER") or None
        if path:
            return path
        return None  # Playwright's own browser

    def available(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False
        exe = self._executable()
        if exe:
            return os.path.exists(exe)
        try:
            with sync_playwright() as p:
                return os.path.exists(p.chromium.executable_path)
        except Exception:  # noqa: BLE001  (no browser installed)
            return False

    def render(self, url: str, fetch: Callable[[str], Fetched | None]) -> Rendered:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RenderFailed("playwright is not installed") from e
        args = ["--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>"]  # no way out but the routes
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")  # Chromium cannot sandbox as root (containers)

        def handle(route) -> None:
            req = route.request
            got = fetch(req.url) if req.method == "GET" else None
            if got is None:
                route.abort("blockedbyclient")
                return
            status, headers, body = got
            route.fulfill(status=status, headers={k: v for k, v in headers.items() if k.lower() not in _DROP}, body=body)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=self._executable(), args=args)
                try:
                    context = browser.new_context(service_workers="block", user_agent=self.user_agent)
                    context.route("**/*", handle)
                    page = context.new_page()
                    page.goto(url, wait_until="networkidle", timeout=self.timeout_s * 1000)
                    return Rendered(page.content(), page.url)
                finally:
                    browser.close()
        except PlaywrightError as e:
            raise RenderFailed(f"{type(e).__name__}: {str(e).splitlines()[0][:120]}") from e


def find_browser(*patterns: str) -> str | None:
    """The first existing Chromium executable matching a glob (for tests and for `OS_RENDER_BROWSER` hints)."""
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            if os.path.isfile(path):
                return path
    return None
