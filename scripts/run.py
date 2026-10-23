"""Build and start the project, then open http://localhost:3000.

Double-click it, or: python scripts/run.py
Starts Docker Desktop (as administrator) if it is not running.

Only what changed is rebuilt. Change only the frontend and only the frontend
image is rebuilt and only its container restarts; the backend, database and
everything else keep running untouched. The same holds for a backend-only
change, or a .env change (only the containers that read it restart).
Data in the Docker volumes (database, Qdrant, uploads) is kept.

For a completely fresh start (empty database, everything rebuilt from zero),
run del.py first and then run.py, or: python scripts/run.py --fresh
"""
import importlib
import subprocess
import sys
import time
import urllib.request
import webbrowser

from _docker import PROJECT, ROOT, ensure_docker, run_script

APP_URL = "http://localhost:3000"
PORTS = (3000, 8000)
START_TIMEOUT_SECONDS = 300


def compose(*args):
    if subprocess.run(["docker", "compose", *args], cwd=ROOT).returncode != 0:
        show_status()
        sys.exit(f"`docker compose {' '.join(args)}` failed. See the output above.")


def show_status():
    subprocess.run(["docker", "compose", "ps", "-a"], cwd=ROOT)
    subprocess.run(["docker", "compose", "logs", "--tail", "40", "migrate", "backend", "frontend"], cwd=ROOT)


def port_owner(port):
    """Name of a container outside this project that publishes `port`, if any."""
    out = subprocess.run(
        ["docker", "ps", "--filter", f"publish={port}", "--format", '{{.Names}}\t{{.Label "com.docker.compose.project"}}'],
        capture_output=True, text=True,
    ).stdout
    for row in out.splitlines():
        name, _, project = row.partition("\t")
        if project != PROJECT:
            return name
    return None


def is_up(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status < 500
    except Exception:
        return False


def main():
    if "--fresh" in sys.argv[1:]:
        # `del` is a Python keyword, so the module cannot be imported by name.
        importlib.import_module("del").wipe()
    else:
        ensure_docker()
    if not (ROOT / ".env").is_file():
        sys.exit(f"Missing {ROOT / '.env'}. Copy .env.example to .env and fill in the keys.")

    for port in PORTS:
        owner = port_owner(port)
        if owner:
            sys.exit(f"Port {port} is used by container '{owner}' from another stack. "
                     "Run del.py (or stop that container) and try again.")

    print("Building what changed and starting containers...")
    compose("up", "-d", "--build", "--remove-orphans")

    print(f"Waiting for {APP_URL} ...")
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while not is_up(APP_URL):
        if time.monotonic() > deadline:
            show_status()
            sys.exit(f"The app did not answer at {APP_URL} within {START_TIMEOUT_SECONDS}s.")
        time.sleep(3)

    print(f"\nPAI is running: {APP_URL}  (API: http://localhost:8000)")
    print("Logs: docker compose logs -f    Stop: docker compose stop")
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    run_script(main)
