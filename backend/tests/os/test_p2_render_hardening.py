"""P2-T4 review fixes: the render sandbox (WebRTC, process, user, limits, deadline) and sub-request rules (R-74)."""

import os
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.render import (
    PlaywrightRenderer,
    RenderFailed,
    RenderLimits,
    SubLimits,
    browser_args,
    find_browser,
)
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


def render_children() -> list[int]:
    """The browser child processes: python running a script named render_child.py (not a shell that mentions it)."""
    out = []
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                argv = (d / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if len(argv) > 1 and b"python" in argv[0] and argv[1].endswith(b"/render_child.py"):
                out.append(int(d.name))
    return out


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
                 "--disable-gpu", "--disable-dev-shm-usage", "--disable-extensions",
                 "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--disable-quic", "--dns-prefetch-disable"):
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
        for pid in render_children():
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


# --- review round 2 -------------------------------------------------------------------------------------------------

@needs_browser
def test_no_name_lookup_websocket_or_webtransport_gets_out(engine, clean, fixture_sites):
    port = fixture_sites.port
    script = (f"var r = ['typeof WebTransport:' + typeof WebTransport];"
              f"try {{ new WebSocket('ws://127.0.0.1:{port}/socket'); r.push('ws-tried'); }} catch (e) {{ r.push('ws-blocked'); }}"
              f"new Image().src = 'http://127.0.0.1:{port}/pixel';"
              "var l = document.createElement('link'); l.rel = 'dns-prefetch'; l.href = '//offlist.test'; document.head.appendChild(l);"
              "fetch('https://offlist.test/x').catch(function () {});"
              "document.getElementById('root').textContent = r.join(' ');")
    url = served(fixture_sites, script)
    plain = direct_fetch(fixture_sites)

    def on_list_only(u, lim):  # what the gateway does: only the allow-listed host is answered
        return plain(u, lim) if f"//{ALPHA}/" in u else None

    out = PlaywrightRenderer(limits()).render(url, on_list_only)
    time.sleep(1)
    assert "typeof WebTransport:undefined" in out.html
    leaked = [(h, p) for h, p in fixture_sites.requests if h.startswith("127.0.0.1") or h == "offlist.test"]
    assert leaked == []  # a WebSocket or an image on the loopback address never reaches the fixture server


@needs_browser
def test_the_browser_is_in_a_cgroup_with_memory_and_process_limits(engine, clean, fixture_sites):
    url = served(fixture_sites, "document.getElementById('root').textContent = 'ok';")
    renderer = PlaywrightRenderer(limits(max_memory_mb=768, max_pids=200))
    seen = {}
    plain = direct_fetch(fixture_sites)

    def fetch(u, lim):
        for pid in render_children():
            try:
                seen["cgroup"] = Path(f"/proc/{pid}/cgroup").read_text()
            except OSError:
                pass
        for kind in ("memory", "pids"):
            for d in Path(f"/sys/fs/cgroup/{kind}").glob("os-render-*"):
                f = d / ("memory.limit_in_bytes" if kind == "memory" else "pids.max")
                seen[kind] = f.read_text().strip()
        return plain(u, lim)

    assert "ok" in renderer.render(url, fetch).html
    if renderer.last_isolation["cgroup"] is None:
        pytest.skip("this host does not let the worker make a cgroup (the RLIMIT_NPROC fallback is tested below)")
    assert renderer.last_isolation["cgroup"] in ("v1", "v2")
    assert "os-render-" in seen["cgroup"]
    if renderer.last_isolation["cgroup"] == "v1":
        assert seen["memory"] == str(768 * 1024 * 1024) and seen["pids"] == "200"
    assert not list(Path("/sys/fs/cgroup/memory").glob("os-render-*"))  # removed afterwards


@needs_browser
@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="the fallback limits the unprivileged user the browser drops to")
def test_without_a_cgroup_the_unprivileged_user_gets_a_process_limit(engine, clean, fixture_sites):
    url = served(fixture_sites, "document.getElementById('root').textContent = 'ok';")
    renderer = PlaywrightRenderer(limits(max_memory_mb=0, max_pids=300))  # 0: no cgroup is made
    seen = {}
    plain = direct_fetch(fixture_sites)

    def fetch(u, lim):
        for pid in render_children():
            try:
                seen["limits"] = Path(f"/proc/{pid}/limits").read_text()
            except OSError:
                pass
        return plain(u, lim)

    assert "ok" in renderer.render(url, fetch).html
    assert renderer.last_isolation == {"cgroup": None, "uid": 65534, "nproc_limit": True}
    line = next(x for x in seen["limits"].splitlines() if x.startswith("Max processes"))
    assert line.split()[2:4] == ["300", "300"]


@needs_browser
def test_the_browser_dies_with_the_worker(engine, clean):
    import signal
    import subprocess
    import sys

    code = (
        "import sys, time\n"
        "from app.os.knowledge.research.render import PlaywrightRenderer, RenderLimits\n"
        f"r = PlaywrightRenderer(RenderLimits(browser_path={BROWSER!r}, timeout_s=60))\n"
        "def fetch(u, lim):\n"
        "    print('asked', flush=True); time.sleep(60)\n"
        "r.render('https://www.alpha-university.test/p', fetch)\n")
    worker = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, cwd=Path(__file__).parents[2])
    try:
        assert worker.stdout.readline().strip() == b"asked"  # the browser is up and waiting for the worker
        assert render_children()
        os.kill(worker.pid, signal.SIGKILL)  # the worker dies without cleaning up
        worker.wait()
        for _ in range(100):
            if not render_children():
                break
            time.sleep(0.1)
        assert render_children() == []
    finally:
        if worker.poll() is None:
            worker.kill()
        from app.os.knowledge.research.render import Cgroup

        time.sleep(0.5)
        Cgroup.sweep(older_than_s=0)  # the dead worker could not remove its own group


def test_the_gateway_waits_for_a_host_that_a_render_just_asked(engine, clean, fixture_sites):
    from datetime import timedelta

    class Clock:
        def __init__(self):
            self.now, self.slept = NOW, []

        def __call__(self):
            return self.now

        def sleep(self, seconds):
            self.slept.append(round(seconds, 3))
            self.now += timedelta(seconds=seconds)

    clock = Clock()
    gw = PageGateway(engine, "pai", load_settings({"DATABASE_URL": "x"}), client=fixture_sites.client(), clock=clock,
                     sleep=clock.sleep)
    gw.pace("www.alpha-university.test", 10)  # a render's sub-request stamps the host
    clock.now += timedelta(seconds=1.5)
    assert clock.slept == []  # nobody asked this host before
    fixture_sites.set_page(ALPHA, "/q", "<html><body>hello there</body></html>")
    assert gw.fetch(f"https://{ALPHA}/q", OWN, []).ok
    assert clock.slept == [0.5]  # the page fetch waited out the rest of the 2 s since the sub-request
    gw.pace("www.alpha-university.test", 0.25)
    assert clock.slept[-1] == 0.25  # and a sub-request never waits longer than the time it has left


def test_empty_cgroups_of_dead_workers_are_swept_but_young_ones_are_left(engine, clean):
    from app.os.knowledge.research.render import Cgroup

    old = Cgroup.create("os-render-stale-test", 64, 10)
    if old is None:
        pytest.skip("this host does not let the worker make a cgroup")
    young = Cgroup.create("os-render-young-test", 64, 10)
    try:
        for d in old.dirs:
            os.utime(d, (time.time() - 3600, time.time() - 3600))
    except OSError:
        old.remove()
        young.remove()
        pytest.skip("cgroup directories cannot be aged here")
    try:
        assert Cgroup.sweep() >= len(old.dirs)
        assert not any(d.exists() for d in old.dirs)
        assert all(d.exists() for d in young.dirs)
    finally:
        old.remove()
        young.remove()
