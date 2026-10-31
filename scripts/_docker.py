"""Shared helpers for run.py and del.py: start Docker Desktop, run docker, keep the window open."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# pai-merge: must match `name:` in docker-compose.yml. Kept apart from a local pai-c stack.
PROJECT = "pai-merge"
DOCKER_START_TIMEOUT_SECONDS = 180


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"docker {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result


def docker_running():
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def docker_desktop_exe():
    """Docker Desktop.exe from the installer's registry entry, else the default install path."""
    try:
        import winreg
        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            folder = Path(winreg.QueryValueEx(handle, "InstallLocation")[0])
    except OSError:
        folder = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker"
    exe = folder / "Docker Desktop.exe"
    return exe if exe.is_file() else None


def ensure_docker():
    """Make sure the Docker engine answers; start Docker Desktop as administrator if it does not."""
    if not shutil.which("docker"):
        sys.exit("Docker is not installed or not on PATH.")
    if docker_running():
        return
    exe = docker_desktop_exe() if sys.platform == "win32" else None
    if not exe:
        sys.exit("Docker is not running. Start Docker Desktop and try again.")
    print("Docker is not running. Starting Docker Desktop as administrator (accept the Windows prompt)...")
    import ctypes
    # "runas" shows the UAC prompt; a result of 32 or less means it failed or was declined.
    if ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), None, None, 1) <= 32:
        sys.exit("Docker Desktop was not started: the administrator prompt was declined.")
    deadline = time.monotonic() + DOCKER_START_TIMEOUT_SECONDS
    while not docker_running():
        if time.monotonic() > deadline:
            sys.exit(f"Docker Desktop did not become ready within {DOCKER_START_TIMEOUT_SECONDS}s.")
        time.sleep(3)
    print("Docker is ready.")


def run_script(main):
    """Run `main`, print any failure, and keep a double-clicked window open until Enter."""
    code = 0
    try:
        main()
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(f"\nERROR: {stop.code}")
            code = 1
        else:
            code = stop.code or 0
    except KeyboardInterrupt:
        print("\nCancelled.")
        code = 1
    if sys.platform == "win32" and sys.stdin.isatty():
        input("\nPress Enter to close...")
    sys.exit(code)
