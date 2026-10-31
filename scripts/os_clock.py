"""Local test only (branch pai-merge): move the PAI OS rehearsal clock forward and run its scheduled jobs.

    python scripts/os_clock.py          move 1 day, then run the jobs ("tick") and wait until they finish
    python scripts/os_clock.py 3        move 3 days (1 to 60), then tick
    python scripts/os_clock.py 0        no move, only tick

In rehearsal mode PAI OS never runs its jobs on its own (no deadlines, reminders, pack building or plan updates
happen by themselves); this is how you make time pass. It talks only to the local stack on http://localhost:8000
with the local admin token from .env (OS_ADMIN_TOKEN, default local-test-admin-token).
"""
import json
import sys
import time
import urllib.error
import urllib.request

from _docker import ROOT, run_script

API = "http://localhost:8000/v1/os/admin/rehearsal"
DEFAULT_TOKEN = "local-test-admin-token"
WAIT_SECONDS = 120


def admin_token():
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OS_ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"') or DEFAULT_TOKEN
    return DEFAULT_TOKEN


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"X-OS-Admin-Token": admin_token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} answered {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach {API} ({e.reason}). Is the app running? Start it with: python scripts/run.py")


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if days:
        moved = call("POST", "/advance", {"days": days})
        print(f"Clock moved {days} day(s): PAI OS date is now {moved['now'][:10]}")
    tick = call("POST", "/tick")["tick_id"]
    print("Running the scheduled jobs...", end="", flush=True)
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        state = call("GET", f"/tick/{tick}")
        if state["status"] != "running":
            break
        if time.monotonic() > deadline:
            sys.exit(f"\nThe jobs are still running after {WAIT_SECONDS}s. Try again in a minute.")
        print(".", end="", flush=True)
        time.sleep(1)
    print(f" {state['status']}")
    if state.get("failed"):
        print(f"Jobs that failed: {', '.join(state['failed'])}  (see: docker compose logs os-worker)")
    print("Wait a few seconds, then reload the page in your browser.")


if __name__ == "__main__":
    run_script(main)
