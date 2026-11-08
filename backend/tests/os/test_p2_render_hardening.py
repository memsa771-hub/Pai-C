"""P2-T4 review fixes: the render sandbox (WebRTC, process, user, limits, deadline) and sub-request rules (R-74)."""

import os
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.render import (PlaywrightRenderer, RenderFailed, RenderLimits, SubLimits, browser_args,
                                              find_browser)
from app.os.settings import load_settings
from tests.os.test_p2_render import ALPHA, OWN

pytestmark = pytest.mark.req("R-74")
NOW = datetime(2027, 5, 2, 10, tzinfo=UTC)
BROWSER = find_browser(os.environ.get("OS_RENDER_BROWSER", ""),
                       "/opt/pw-browsers/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
                       "/usr/bin/google-chrome", "/usr/bin/chromium")
needs_browser = pytest.mark.skipif(BROWSER is None or not PlaywrightRenderer(browser_path=BROWSER).available(),
                                   reason="no headless Chromium found")
SHELL = "<html><head><script src='/static/p.js'></script></head><body><div id='root'></div></body></html>"


def limits(**kw) -> RenderLimits:
    return RenderLimits(browser_path=BROWSER, **kw)


def ready(script: str) -> str:
    """The script runs once the page body exists (the shell's script tag is in the head)."""
    return "document.addEventListener('DOMContentLoaded', function () {" + script + "});"


def served(sites, script: str, path: str = "/p") -> str:
    sites.set_page(ALPHA, path, SHELL)
    sites.set_page(ALPHA, "/static/p.js", ready(script), "application/javascript")
    return f"https://{ALPHA}{path}"


def direct_fetch(sites, calls=None):
    """A sub-request answerer for tests of the renderer alone: serves what the fixture site holds."""
    client = sites.client()

    def fetch(url: str, lim: SubLimits):
        if calls is not None:
            calls.append(url)
        r = client.get(url, follow_redirects=False)
        return r.status_code, dict(r.headers), r.content
    return fetch


def processes_with(text: str) -> list[int]:
    out = []
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                if text in (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace"):
                    out.append(int(d.name))
            except OSError:
                pass
    return out


# --- launch flags ---------------------------------------------------------------------------------------------------

def test_browser_args_close_webrtc_limit_memory_and_keep_the_sandbox_by_default():
    args = browser_args(RenderLimits(max_old_space_mb=256))
    for flag in ("--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                 "--webrtc-ip-handling-policy=disable_non_proxied_udp", "--js-flags=--max-old-space-size=256",
                 "--disable-gpu", "--disable-dev-shm-usage", "--disable-extensions"):
        assert flag in args
    assert "--no-sandbox" not in args
    assert "--no-sandbox" in browser_args(RenderLimits(no_sandbox=True))


# --- WebRTC ---------------------------------------------------------------------------------------------------------

@needs_browser
def test_a_page_cannot_use_webrtc(engine, clean, fixture_sites):
    script = ("var r = ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCDataChannel'].map(function (n) {"
              " return n + ':' + typeof window[n]; });"
              "try { new RTCPeerConnection(); r.push('constructed'); } catch (e) { r.push('blocked'); }"
              "document.getElementById('root').textContent = r.join(' ');")
    url = served(fixture_sites, script)
    out = PlaywrightRenderer(limits()).render(url, direct_fetch(fixture_sites))
    assert ("RTCPeerConnection:undefined webkitRTCPeerConnection:undefined RTCDataChannel:undefined blocked"
            in out.html)


# --- the process: user and limits -----------------------------------------------------------------------------------

@needs_browser
def test_the_browser_runs_in_its_own_process_as_an_unprivileged_user_with_limits(engine, clean, fixture_sites, request):
    url = served(fixture_sites, "document.getElementById('root').textContent = 'ok';")
    tmp_path = Path(tempfile.mkdtemp(prefix="rt-"))  # pytest's tmp_path has private parents; the browser user must reach this
    tmp_path.chmod(0o755)
    request.addfinalizer(lambda: shutil.rmtree(tmp_path, ignore_errors=True))
    seen = {}
    plain = direct_fetch(fixture_sites)

    def fetch(u, lim):
        for pid in processes_with("render_child.py"):
            try:
                status = Path(f"/proc/{pid}/status").read_text()
                seen["uid"] = int(next(line for line in status.splitlines() if line.startswith("Uid:")).split()[1])
                seen["limits"] = Path(f"/proc/{pid}/limits").read_text()
            except OSError:
                pass
        return plain(u, lim)

    assert "ok" in PlaywrightRenderer(limits(work_root=str(tmp_path))).render(url, fetch).html
    expected = 65534 if os.geteuid() == 0 else os.geteuid()
    assert seen["uid"] == expected
    assert os.geteuid() != 0 or seen["uid"] != 0  # as root, the browser is never root
    core = next(line for line in seen["limits"].splitlines() if line.startswith("Max core file size"))
    assert core.split()[4:6] == ["0", "0"]
    assert not any(tmp_path.iterdir())  # the private working directory is removed


# --- the deadline ---------------------------------------------------------------------------------------------------

@needs_browser
def test_a_page_that_never_lets_go_ends_within_the_deadline_with_no_process_left(engine, clean, fixture_sites):
    url = served(fixture_sites, "while (true) {}")
    before = set(processes_with("os-render-"))
    start = time.monotonic()
    with pytest.raises(RenderFailed):
        PlaywrightRenderer(limits(timeout_s=5)).render(url, direct_fetch(fixture_sites))
    assert time.monotonic() - start < 5 + 6
    time.sleep(0.5)
    assert set(processes_with("os-render-")) == before  # no child, driver or Chromium process is left


@needs_browser
def test_nothing_is_requested_after_the_deadline_and_the_browser_is_killed(engine, clean, fixture_sites):
    url = served(fixture_sites, "document.getElementById('root').textContent = 'late';")
    calls: list[str] = []
    before = set(processes_with("os-render-"))

    def slow(u, lim):
        calls.append(u)
        time.sleep(4)  # the first answer already uses the whole deadline
        return None

    start = time.monotonic()
    with pytest.raises(RenderFailed, match="deadline"):
        PlaywrightRenderer(limits(timeout_s=3)).render(url, slow)
    assert len(calls) == 1 and time.monotonic() - start < 3 + 4 + 3
    time.sleep(0.5)
    assert set(processes_with("os-render-")) == before  # the hard kill took the whole process group


# --- sub-request limits ---------------------------------------------------------------------------------------------

@needs_browser
def test_the_number_of_sub_requests_is_capped(engine, clean, fixture_sites):
    script = ("for (let i = 0; i < 15; i++) { fetch('/api/n' + i).catch(function () {}); }"
              "document.getElementById('root').textContent = 'done';")
    url = served(fixture_sites, script)
    calls: list[str] = []
    PlaywrightRenderer(limits(max_requests=4)).render(url, direct_fetch(fixture_sites, calls))
    assert len(calls) == 4  # the page, the script and two more


@needs_browser
def test_the_total_bytes_of_sub_requests_are_capped(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/big.js", ready("var big = '" + "x" * 5000 + "'; document.getElementById('root').textContent = 'big';"),
                           "application/javascript")
    fixture_sites.set_page(ALPHA, "/p", SHELL.replace("/static/p.js", "/big.js"))
    out = PlaywrightRenderer(limits(max_bytes=2000)).render(f"https://{ALPHA}/p", direct_fetch(fixture_sites))
    assert "big</div>" not in out.html  # the script was over the byte budget and was refused


def gateway(engine, sites, renderer, **env):
    return PageGateway(engine, "pai", load_settings({"DATABASE_URL": "x", **env}), client=sites.client(),
                       clock=lambda: NOW, sleep=env.pop("sleeps", lambda s: None), renderer=renderer)


@needs_browser
def test_sub_requests_obey_robots_txt(engine, clean, fixture_sites):
    script = ("fetch('/private/data').then(function (r) { document.getElementById('root').textContent = 'got ' + r.status; })"
              ".catch(function () { document.getElementById('root').textContent = 'refused'; });")
    url = served(fixture_sites, script)
    page = gateway(engine, fixture_sites, PlaywrightRenderer(limits())).fetch(url, OWN, [])
    assert page.ok and "refused" in page.text
    assert all(path != "/private/data" for _, path in fixture_sites.requests)  # never asked: robots.txt says no


@needs_browser
def test_sub_requests_wait_the_host_interval(engine, clean, fixture_sites):
    url = served(fixture_sites, "document.getElementById('root').textContent = 'paced';")
    sleeps: list[float] = []
    gw = PageGateway(engine, "pai", load_settings({"DATABASE_URL": "x"}), client=fixture_sites.client(),
                     clock=lambda: NOW, sleep=sleeps.append, renderer=PlaywrightRenderer(limits()))
    assert gw.fetch(url, OWN, []).ok
    assert [s for s in sleeps if s > 0]  # the page's own fetch, then each sub-request, wait the interval


@needs_browser
def test_a_sub_request_over_the_size_limit_is_refused_while_streaming(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/static/big.js", ready("document.getElementById('root').textContent = 'x';") + "// " + "x" * 5000, "application/javascript")
    fixture_sites.set_page(ALPHA, "/p", SHELL.replace("/static/p.js", "/static/big.js"))
    gw = gateway(engine, fixture_sites, PlaywrightRenderer(limits()), OS_PAGE_MAX_BYTES="2000")
    page = gw.fetch(f"https://{ALPHA}/p", OWN, [])
    assert page.blocked == "not_readable:render"  # the script was refused, so the page stayed empty
