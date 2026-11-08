"""Headless reading for JavaScript pages (P2 spec §4.3, P2-D12; R-74).

When a fetched page is a JavaScript shell (little visible text, scripts present), the gateway renders it and reads the
resulting DOM (`read_method: render`). The browser is the least trusted thing the gateway runs, so:

- **No network of its own.** Chromium is launched with a dead proxy; every request it makes (page, scripts, XHR,
  redirects) is intercepted in the browser process and answered by THIS process through the gateway's own HTTP client,
  only for GET and only for URLs the allow-list accepts. Service workers are blocked, WebRTC is switched off (launch
  flags and an init script), and WebSockets cannot connect (nothing to connect through). This is the egress rule of
  `app/browser/egress.py` reached from the other side (no Counsellor code is imported: Tach).
- **Its own process.** The browser runs in a child process (`render_child.py`) in its own session, with CPU, file-size and
  core-dump limits, an empty environment and a private working directory. If the worker runs as root, the child drops to an
  unprivileged user (`run_as_uid`, 65534 by default) and Chromium keeps its sandbox; only `no_sandbox` removes it, and
  only when an operator sets it.
- **One deadline.** `render()` has a single wall-clock deadline. When it passes, the child's whole process group is killed
  (SIGKILL), whatever the browser was doing (Playwright's `content()` has no timeout argument of its own).
- **Limits on sub-requests.** At most `max_requests` of them and `max_bytes` in total; none after the deadline.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import resource
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CHILD_SCRIPT = Path(__file__).with_name("render_child.py")
# What a request may be answered with: status, headers, body. None refuses the request.
Fetched = tuple[int, dict[str, str], bytes]
_DROP = {"content-encoding", "content-length", "transfer-encoding", "connection"}  # the client already decoded the body

# A page must not get an IP address out of the browser, or a data channel to anywhere (P2-T4 review).
WEBRTC_BLOCK_SCRIPT = """
for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCDataChannel']) {
  try { delete window[name]; } catch (e) {}
  try { Object.defineProperty(window, name, {value: undefined, configurable: false, writable: false}); } catch (e) {}
}
"""


class RenderFailed(Exception):
    """The page could not be rendered (no browser, deadline, navigation refused or failed)."""


@dataclass(frozen=True)
class Rendered:
    html: str
    final_url: str


@dataclass(frozen=True)
class SubLimits:
    """What one sub-request may still use: seconds before the deadline and bytes before the total is spent."""
    time_left_s: float
    max_bytes: int


@dataclass(frozen=True)
class RenderLimits:
    timeout_s: float = 30.0
    max_requests: int = 60
    max_bytes: int = 20_000_000
    max_old_space_mb: int = 512
    run_as_uid: int | None = 65534
    no_sandbox: bool = False
    browser_path: str | None = None
    user_agent: str | None = None
    work_root: str | None = None  # where the private working directories are made (default: the system temp)

    @classmethod
    def from_settings(cls, settings, user_agent: str | None = None) -> RenderLimits:
        return cls(timeout_s=settings.render_timeout_s, max_requests=settings.render_max_requests,
                   max_bytes=settings.render_max_bytes, max_old_space_mb=settings.render_max_old_space_mb,
                   run_as_uid=settings.render_run_as_uid, no_sandbox=settings.render_no_sandbox,
                   browser_path=settings.render_browser_path, user_agent=user_agent)


def looks_like_js_shell(html: str, visible_text: str, max_chars: int) -> bool:
    """A little visible text (thresholds in settings) and scripts in the page: the content is built by JavaScript."""
    return len(visible_text.strip()) < max_chars and "<script" in html.lower()


def browser_args(limits: RenderLimits) -> list[str]:
    args = [
        "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",  # no way out but the routes
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        f"--js-flags=--max-old-space-size={limits.max_old_space_mb}",
        "--disable-gpu", "--disable-dev-shm-usage", "--disable-extensions",
    ]
    if limits.no_sandbox:
        args.append("--no-sandbox")  # only when an operator says the host cannot start Chromium's sandbox
    return args


def _drops_privileges(limits: RenderLimits) -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0 and limits.run_as_uid is not None


def _preexec(uid: int | None, cpu_s: int) -> Callable[[], None]:
    def run() -> None:
        os.setsid()  # its own session and process group: the deadline kills the whole group
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100_000_000, 100_000_000))
        if uid is not None:
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
    return run


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover  (SIGKILL cannot be ignored)
        pass


class _Pipe:
    """Line reader and writer on the child's pipes that never waits past the deadline."""

    def __init__(self, proc: subprocess.Popen, deadline: float) -> None:
        self.proc, self.deadline, self.buf = proc, deadline, b""

    def readline(self) -> dict:
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.buf:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise RenderFailed("render deadline passed")
            ready, _, _ = select.select([fd], [], [], min(left, 0.5))
            if ready:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    raise RenderFailed(f"browser process ended without an answer (exit {self.proc.poll()})")
                self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return json.loads(line)

    def write(self, obj: dict) -> None:
        data = (json.dumps(obj) + "\n").encode()
        fd = self.proc.stdin.fileno()
        while data:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise RenderFailed("render deadline passed")
            _, ready, _ = select.select([], [fd], [], min(left, 0.5))
            if ready:
                data = data[os.write(fd, data[:65536]):]


class PlaywrightRenderer:
    name = "playwright"

    def __init__(self, limits: RenderLimits | None = None, *, timeout_s: float | None = None,
                 browser_path: str | None = None, user_agent: str | None = None) -> None:
        base = limits or RenderLimits()
        self.limits = RenderLimits(**{**base.__dict__, **{k: v for k, v in (
            ("timeout_s", timeout_s), ("browser_path", browser_path), ("user_agent", user_agent)) if v is not None}})

    def _executable(self) -> str | None:
        return self.limits.browser_path or os.environ.get("OS_RENDER_BROWSER") or None

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

    def _executable_or_default(self) -> str:
        exe = self._executable()
        if exe:
            return exe
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                return p.chromium.executable_path
        except Exception as e:
            raise RenderFailed("no browser to run") from e

    def render(self, url: str, fetch: Callable[[str, SubLimits], Fetched | None]) -> Rendered:
        lim = self.limits
        deadline = time.monotonic() + lim.timeout_s
        exe = self._executable_or_default()
        if not os.path.exists(exe):
            raise RenderFailed("browser executable not found")
        uid = lim.run_as_uid if _drops_privileges(lim) else None
        root = Path(tempfile.mkdtemp(prefix="os-render-", dir=lim.work_root))
        proc = None
        try:
            root.chmod(0o755)
            script = root / "render_child.py"
            script.write_text(CHILD_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
            script.chmod(0o644)
            work = root / "w"
            work.mkdir(mode=0o700)
            if uid is not None:
                os.chown(work, uid, uid)
            cfg = {"url": url, "executable": exe, "args": browser_args(lim), "user_agent": lim.user_agent,
                   "init_script": WEBRTC_BLOCK_SCRIPT, "timeout_ms": int(max(1.0, lim.timeout_s - 2) * 1000)}
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work), "TMPDIR": str(work),
                   "LANG": "C.UTF-8"}
            if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
                env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
            try:
                proc = subprocess.Popen(
                    [sys.executable, str(script), json.dumps(cfg)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, cwd=work, env=env,
                    preexec_fn=_preexec(uid, int(lim.timeout_s * 2) + 10))  # noqa: PLW1509  (a new session is the point)
            except OSError as e:
                raise RenderFailed(f"browser process did not start: {type(e).__name__}") from e
            return self._serve(proc, fetch, deadline)
        finally:
            if proc is not None:
                _kill_group(proc)
            shutil.rmtree(root, ignore_errors=True)

    def _serve(self, proc: subprocess.Popen, fetch, deadline: float) -> Rendered:
        lim, pipe = self.limits, _Pipe(proc, deadline)
        requests = total = 0
        while True:
            msg = pipe.readline()
            op = msg.get("op")
            if op == "done":
                return Rendered(msg["html"], msg["url"])
            if op == "error":
                raise RenderFailed(msg.get("message", "render failed"))
            if op != "get":
                raise RenderFailed("unknown message from the browser process")
            answer: dict = {"refused": True}
            left = deadline - time.monotonic()
            if requests < lim.max_requests and total < lim.max_bytes and left > 0:  # nothing after the deadline
                requests += 1
                try:
                    got = fetch(msg["url"], SubLimits(left, lim.max_bytes - total))
                except Exception:  # noqa: BLE001  (a sub-request that fails is a sub-request that is refused)
                    got = None
                if got is not None and total + len(got[2]) <= lim.max_bytes:
                    status, headers, body = got
                    total += len(body)
                    answer = {"status": status, "body_b64": base64.b64encode(body).decode(),
                              "headers": {k: v for k, v in headers.items() if k.lower() not in _DROP}}
            pipe.write(answer)


def find_browser(*patterns: str) -> str | None:
    """The first existing Chromium executable matching a glob (for tests and for `OS_RENDER_BROWSER` hints)."""
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            if os.path.isfile(path):
                return path
    return None
