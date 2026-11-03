#!/usr/bin/env python3
"""pai.py: one file that takes a Ubuntu server from nothing to a live
Placement AI stack behind Caddy, and runs it afterwards.

Copy this one file to any Ubuntu server (or run it from a checkout) and:

    python3 pai.py deploy            fresh server -> live (installs Docker,
                                          Caddy, clones the repo, asks for the
                                          secrets, builds, hosts; safe to re-run)
    python3 pai.py update            git pull, rebuild what changed, check
    python3 pai.py status            is everything running? (containers,
                                          RAM, disk, health, live URLs)
    python3 pai.py logs              follow backend + worker logs
    python3 pai.py backup            Postgres dump -> backups/
    python3 pai.py restore FILE      restore a dump
    python3 pai.py export            everything (db, uploads, .env,
                                          secrets) -> one .tar.gz
    python3 pai.py import FILE       load an export on this server
    python3 pai.py migrate-from USER@OLDHOST[:DIR]
                                          export on the old server over ssh,
                                          copy here, import, deploy
    python3 pai.py env KEY=VALUE ... set .env values, restart backend+worker
    python3 pai.py restart|stop|start

Only the Python standard library is used, so it runs on a bare Ubuntu 22.04 or
24.04 (python3 is preinstalled). Everything it decides is printed; secrets are
never printed. Details: docs/DEPLOY.md.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets as _secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_URL = "https://github.com/memsa771-hub/Pai-beta.git"
REPO_BRANCH = "main"
DEFAULT_DIR = Path.home() / "pai-c"
COMPOSE_FILE = "docker-compose.prod.yml"
PROJECT = "pai-beta"                       # `name:` in docker-compose.prod.yml
APP_DOMAIN = "app.placement-ai.com"        # fixed in docker-compose.prod.yml (CORS gate)
API_DOMAIN = "api.placement-ai.com"
PROXY_NETWORK_HOST = "pai-beta_proxy"      # external network when the proxy is on the host
FRONTEND_ALIAS, BACKEND_ALIAS = "pai-frontend", "pai-backend"
MARK_BEGIN, MARK_END = "# >>> pai-beta (managed by pai.py) >>>", "# <<< pai-beta <<<"
MIN_RAM_GB, GOOD_RAM_GB, MIN_DISK_GB = 1.5, 3.5, 8.0
DB_NAME, DB_USER = "openagents_workspace", "pai_admin"
FIREBASE_FILE = Path("secrets/firebase-service-account.json")

# .env keys deploy asks for when they are empty: (key, prompt, secret?, required?)
ENV_PROMPTS = [
    ("FIREBASE_PROJECT_ID", "Firebase project id", False, True),
    ("NEXT_PUBLIC_FIREBASE_API_KEY", "Firebase web API key", False, True),
    ("NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN", "Firebase auth domain (xxx.firebaseapp.com)", False, True),
    ("NEXT_PUBLIC_FIREBASE_APP_ID", "Firebase web app id", False, True),
    ("PAI_API_KEY", "OpenAI API key", True, True),
    ("ANTHROPIC_API_KEY", "Anthropic API key (Enter = chat runs on OpenAI)", True, False),
    ("RESEND_API_KEY", "Resend API key (account emails)", True, True),
    ("WEB_SEARCH_API_KEY", "Tavily API key (web research; Enter = none)", True, False),
    ("PAI_FOUNDER_EMAILS", "Founder email(s) for the usage page, comma separated", False, False),
]

ARGS: argparse.Namespace
LOG_PATH: Path | None = None


# --------------------------------------------------------------------------- output
def say(msg: str = "") -> None:
    print(msg, flush=True)
    if LOG_PATH:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")


def step(msg: str) -> None:
    say(f"\n==> {msg}")


def die(msg: str, code: int = 1) -> None:
    say(f"\nERROR: {msg}")
    sys.exit(code)


def confirm(question: str, default: bool = True) -> bool:
    if getattr(ARGS, "yes", False):
        return True
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(question + suffix).strip().lower()
    return default if not answer else answer.startswith("y")


# --------------------------------------------------------------------------- shell
def run(cmd: list[str], check: bool = True, capture: bool = True, quiet: bool = False,
        env: dict | None = None, inp: str | None = None) -> subprocess.CompletedProcess:
    """Run a command; captured output is returned, not printed."""
    if not quiet:
        say("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, input=inp,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None, env=env)


def out(cmd: list[str], **kw) -> str:
    return run(cmd, quiet=True, check=kw.pop("check", True), **kw).stdout.strip()


def stream(cmd: list[str], cwd: Path | None = None) -> int:
    """Run a long command, showing its output live and keeping it in the log."""
    say("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        say(line.rstrip("\n"))
    return proc.wait()


def sudo(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return run(cmd if os.geteuid() == 0 else ["sudo", *cmd], **kw)


def sudo_write(path: str, text: str, mode: str = "644") -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pai") as tmp:
        tmp.write(text)
    sudo(["install", "-m", mode, tmp.name, path], quiet=True)
    os.unlink(tmp.name)


def sudo_read(path: str) -> str:
    return sudo(["cat", path], quiet=True, check=False).stdout


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


# --------------------------------------------------------------------------- docker
_DOCKER: list[str] | None = None


def docker_cmd() -> list[str]:
    """`docker` or `sudo docker`, whichever works for this user right now."""
    global _DOCKER
    if _DOCKER is None:
        if run(["docker", "info"], check=False, quiet=True).returncode == 0:
            _DOCKER = ["docker"]
        elif run(["sudo", "-n", "docker", "info"], check=False, quiet=True).returncode == 0:
            _DOCKER = ["sudo", "docker"]
        else:
            die("docker is not usable by this user. Log out and in again (docker group), then re-run.")
    return _DOCKER


def compose(*args: str, **kw) -> subprocess.CompletedProcess:
    return run([*docker_cmd(), "compose", "-f", COMPOSE_FILE, *args], **kw)


def compose_stream(*args: str) -> int:
    return stream([*docker_cmd(), "compose", "-f", COMPOSE_FILE, *args], cwd=ARGS.dir)


def docker_json(*args: str) -> list:
    text = out([*docker_cmd(), *args, "--format", "{{json .}}"], check=False)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# --------------------------------------------------------------------------- .env helpers (pure)
def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def set_env_values(text: str, updates: dict[str, str]) -> str:
    """Set keys in .env text: replace the key's line (uncommenting `# KEY=` if
    that is all there is), else append. Order and comments are kept."""
    lines = text.splitlines()
    done: set[str] = set()
    for i, line in enumerate(lines):
        for key, value in updates.items():
            if key in done:
                continue
            if re.match(rf"^\s*(#\s*)?{re.escape(key)}\s*=", line):
                lines[i] = f"{key}={value}"
                done.add(key)
                break
    for key, value in updates.items():
        if key not in done:
            lines.append(f"{key}={value}")
    return "\n".join(lines).rstrip("\n") + "\n"


def splice_block(text: str, block: str) -> str:
    """Put `block` between the markers, replacing an earlier managed block."""
    managed = f"{MARK_BEGIN}\n{block.strip()}\n{MARK_END}\n"
    pattern = re.compile(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n?", re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: managed, text, count=1)
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + managed


def render_caddy_blocks(frontend: str, backend: str) -> str:
    """Caddy site blocks; `frontend`/`backend` are upstreams like 127.0.0.1:3001."""
    body = "\tencode gzip\n\trequest_body {\n\t\tmax_size 50MB\n\t}\n"
    return (f"{APP_DOMAIN} {{\n{body}\treverse_proxy {frontend}\n}}\n\n"
            f"{API_DOMAIN} {{\n{body}\treverse_proxy {backend}\n}}\n")


def pick_port(preferred: int, used: set[int]) -> int:
    port = preferred
    while port in used:
        port += 1
    return port


def is_stock_caddyfile(text: str) -> bool:
    """True for the placeholder Caddyfile the caddy package installs (a lone
    `:80` file server), which deploy replaces instead of keeping."""
    code = "\n".join(l for l in text.splitlines() if l.strip() and not l.strip().startswith("#"))
    return not code.strip() or re.fullmatch(r":80\s*\{[^{}]*\}", code.strip()) is not None


# --------------------------------------------------------------------------- system facts
def mem_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / 1024 / 1024
    return 0.0


def swap_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("SwapTotal:"):
            return int(line.split()[1]) / 1024 / 1024
    return 0.0


def disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1024 ** 3


def listening_ports() -> dict[int, str]:
    """{port: process name} for every TCP listener (empty name when unknown)."""
    ports: dict[int, str] = {}
    text = sudo(["ss", "-ltnpH"], check=False, quiet=True).stdout or ""   # root sees every owner
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        try:
            port = int(local.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            continue
        match = re.search(r'users:\(\("([^"]+)"', line)
        ports[port] = match.group(1) if match else ports.get(port, "")
    return ports


def public_ip() -> str:
    for url in ("https://checkip.amazonaws.com", "https://api.ipify.org"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    return ""


def http_get(url: str, timeout: int = 10) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "pai.py"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(300).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return 0, str(exc)


def wait_for(url: str, want: int = 200, seconds: int = 120, label: str = "") -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        status, _ = http_get(url)
        if status == want:
            say(f"ok  {label or url}")
            return True
        time.sleep(5)
    say(f"NOT ok  {label or url} (last status {status})")
    return False


# --------------------------------------------------------------------------- deploy steps
def preflight() -> None:
    step("Checking this server")
    if sys.platform != "linux":
        die("pai.py runs on the Ubuntu server, not on Windows/macOS.")
    if os.geteuid() != 0 and run(["sudo", "-n", "true"], check=False, quiet=True).returncode != 0:
        say("sudo will ask for your password once.")
        run(["sudo", "-v"], capture=False, quiet=True)
    ram = mem_gb()
    say(f"RAM {ram:.1f} GB, swap {swap_gb():.1f} GB, free disk {disk_free_gb(Path.home()):.1f} GB, "
        f"{os.cpu_count()} vCPU")
    if ram < MIN_RAM_GB and not ARGS.force:
        die(f"{ram:.1f} GB RAM is not enough: this stack needs 4 GB (t3.medium or larger). "
            "Resize the instance, or pass --force to try anyway.")
    if ram < GOOD_RAM_GB:
        say(f"WARNING: {ram:.1f} GB RAM is below the 4 GB this stack is sized for; adding swap.")
    if disk_free_gb(Path.home()) < MIN_DISK_GB:
        say("Disk is tight; pruning unused Docker data.")
        if have("docker"):
            run([*docker_cmd(), "system", "prune", "-f"], check=False, capture=False)
        if disk_free_gb(Path.home()) < MIN_DISK_GB:
            die(f"Less than {MIN_DISK_GB:.0f} GB free; grow the volume (docs/DEPLOY.md, section 9).")


def apt_install(*packages: str) -> None:
    quiet = ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "-qq"]
    sudo([*quiet, "update"], capture=False)
    sudo([*quiet, "install", "-y", *packages], capture=False)


def ensure_base_packages() -> None:
    step("System update and base packages")
    apt_install("ca-certificates", "curl", "git", "openssl")


def ensure_swap() -> None:
    if swap_gb() > 0 or mem_gb() >= 6:
        return
    step("Adding 2 GB swap (build safety)")
    if Path("/swapfile").exists():
        sudo(["swapon", "/swapfile"], check=False, capture=False)
        return
    sudo(["fallocate", "-l", "2G", "/swapfile"], capture=False)
    sudo(["chmod", "600", "/swapfile"], capture=False)
    sudo(["mkswap", "/swapfile"], capture=False)
    sudo(["swapon", "/swapfile"], capture=False)
    if "/swapfile" not in sudo_read("/etc/fstab"):
        sudo(["sh", "-c", "echo '/swapfile none swap sw 0 0' >> /etc/fstab"], quiet=True)


def ensure_docker() -> None:
    step("Docker")
    if not have("docker"):
        say("Installing Docker (get.docker.com)")
        script = out(["curl", "-fsSL", "https://get.docker.com"])
        sudo(["sh"], inp=script, capture=False)
    if os.geteuid() != 0:
        user = os.environ.get("USER") or getpass.getuser()
        groups = out(["id", "-nG"]).split()
        if "docker" not in groups:
            sudo(["usermod", "-aG", "docker", user], capture=False)
            say(f"{user} added to the docker group (takes effect at your next login; "
                "sudo is used meanwhile).")
    global _DOCKER
    _DOCKER = None
    say("docker compose " + out([*docker_cmd(), "compose", "version", "--short"], check=False))


def ensure_checkout() -> None:
    step(f"Code at {ARGS.dir}")
    target = ARGS.dir
    if (target / COMPOSE_FILE).exists():
        if (target / ".git").exists() and not ARGS.no_pull:
            run(["git", "-C", str(target), "fetch", "--quiet", "origin"], check=False, capture=False)
            run(["git", "-C", str(target), "pull", "--ff-only", "--quiet"], check=False, capture=False)
        say("commit " + out(["git", "-C", str(target), "rev-parse", "--short", "HEAD"], check=False))
        return
    if target.exists() and any(target.iterdir()):
        die(f"{target} exists and is not a checkout of the stack. Use --dir for another folder.")
    run(["git", "clone", "--branch", ARGS.branch, ARGS.repo, str(target)], capture=False)
    global LOG_PATH
    LOG_PATH = target / "pai.log"


def read_firebase_json(path_hint: str | None) -> str:
    if path_hint:
        text = Path(path_hint).expanduser().read_text()
        json.loads(text)
        return text
    say("Paste the Firebase service-account JSON (from Firebase console, Project settings, "
        "Service accounts, Generate new private key). Paste it all, then press Enter on an empty line.")
    lines: list[str] = []
    blanks = 0
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        if not line.strip():
            blanks += 1
            try:
                json.loads("\n".join(lines))
                break
            except json.JSONDecodeError:
                if blanks >= 3:
                    break
                continue
        blanks = 0
        lines.append(line.rstrip("\n"))
    text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        die("That was not valid JSON. Save the file on your computer and pass --firebase-json PATH.")
    if data.get("type") != "service_account":
        die("That JSON is not a Firebase service account (expected \"type\": \"service_account\").")
    return text


def ensure_env() -> dict[str, str]:
    step("Secrets (.env and the Firebase service account)")
    env_path = ARGS.dir / ".env"
    if ARGS.env_file and not env_path.exists():
        shutil.copy(Path(ARGS.env_file).expanduser(), env_path)
        say(f"copied {ARGS.env_file} -> .env")
    if not env_path.exists():
        shutil.copy(ARGS.dir / ".env.production.example", env_path)
        say("created .env from .env.production.example")
    text = env_path.read_text()
    values = parse_env(text)
    updates: dict[str, str] = {}
    if not values.get("DB_PASSWORD"):
        updates["DB_PASSWORD"] = _secrets.token_hex(24)
        say("DB_PASSWORD generated")
    for key, prompt, secret, required in ENV_PROMPTS:
        if values.get(key):
            continue
        if ARGS.yes:
            if required:
                die(f".env is missing {key}; fill it or run without --yes to be asked.")
            continue
        while True:
            answer = (getpass.getpass(f"{prompt}: ") if secret else input(f"{prompt}: ")).strip()
            if answer or not required:
                break
            say("Required.")
        if answer:
            updates[key] = answer
    merged = {**values, **updates}
    if not merged.get("MEMORY_EMBEDDING_API_KEY") and merged.get("PAI_API_KEY"):
        updates["MEMORY_EMBEDDING_API_KEY"] = merged["PAI_API_KEY"]
    for key in ("APP_ENV", "CORS_ORIGINS", "APP_URL", "FRONTEND_BASE_URL", "NEXT_PUBLIC_API_URL"):
        if key in values:
            say(f"removing {key} from .env (the compose file owns it)")
            text = re.sub(rf"^\s*{key}\s*=.*\n?", "", text, flags=re.M)
    if updates:
        text = set_env_values(text, updates)
    env_path.write_text(text)
    os.chmod(env_path, 0o600)
    firebase = ARGS.dir / FIREBASE_FILE
    if not firebase.exists():
        if ARGS.yes and not ARGS.firebase_json:
            die(f"{FIREBASE_FILE} is missing; pass --firebase-json PATH.")
        firebase.parent.mkdir(parents=True, exist_ok=True)
        firebase.write_text(read_firebase_json(ARGS.firebase_json))
        os.chmod(firebase, 0o600)
        say(f"wrote {FIREBASE_FILE}")
    (ARGS.dir / "proposals").mkdir(exist_ok=True)
    (ARGS.dir / "backups").mkdir(exist_ok=True)
    return parse_env(text)


class Proxy:
    """What owns ports 80/443 here and how our site blocks reach it."""
    kind: str = "none"            # none | caddy-host | caddy-docker | nginx-host
    container: str = ""           # caddy-docker
    network: str = ""             # caddy-docker
    caddyfile: str = "/etc/caddy/Caddyfile"


def detect_proxy() -> Proxy:
    proxy = Proxy()
    owner = listening_ports().get(443, None)
    if owner is None:
        proxy.kind = "none"
        return proxy
    if owner == "caddy":
        proxy.kind = "caddy-host"
        return proxy
    if owner == "nginx":
        proxy.kind = "nginx-host"
        return proxy
    if owner in ("docker-proxy", "dockerd", ""):
        for row in docker_json("ps"):
            ports, image, name = row.get("Ports", ""), row.get("Image", ""), row.get("Names", "")
            if ":443->" in ports and ("caddy" in image or "caddy" in name):
                proxy.kind = "caddy-docker"
                proxy.container = name
                info = json.loads(out([*docker_cmd(), "inspect", name]))[0]
                nets = [n for n in info["NetworkSettings"]["Networks"] if n != "bridge"]
                proxy.network = nets[0] if nets else "bridge"
                for mount in info.get("Mounts", []):
                    if mount.get("Destination") == "/etc/caddy/Caddyfile":
                        proxy.caddyfile = mount["Source"]
                    elif mount.get("Destination") == "/etc/caddy":
                        proxy.caddyfile = str(Path(mount["Source"]) / "Caddyfile")
                return proxy
        die(f"Port 443 is held by a Docker container that is not Caddy ({owner}). "
            "Stop it, or run the stack behind it by hand (docs/DEPLOY.md, section 5).")
    die(f"Port 443 is held by '{owner}'. Stop it or use it as the proxy by hand (docs/DEPLOY.md).")
    return proxy


def ensure_ports(values: dict[str, str], proxy: Proxy) -> tuple[int, int]:
    """Host ports for frontend/backend that are free (or already ours)."""
    ours = {int(r["Ports"].split(":")[1].split("->")[0]) for r in docker_json("ps")
            if r.get("Names", "").startswith(PROJECT + "-") and "->" in r.get("Ports", "")
            and r["Ports"].split(":")[1].split("->")[0].isdigit()}
    used = set(listening_ports()) - ours
    want_front = int(values.get("FRONTEND_PORT") or 3000)
    want_back = int(values.get("BACKEND_PORT") or 8000)
    front, back = pick_port(want_front, used), pick_port(want_back, used | {want_front})
    updates = {}
    if front != want_front:
        say(f"port {want_front} is taken; frontend will use {front}")
        updates["FRONTEND_PORT"] = str(front)
    if back != want_back:
        say(f"port {want_back} is taken; backend will use {back}")
        updates["BACKEND_PORT"] = str(back)
    if proxy.kind == "caddy-docker":
        if values.get("PROXY_NETWORK") != proxy.network:
            updates["PROXY_NETWORK"] = proxy.network
            say(f"stack joins the Caddy container's network {proxy.network}")
    elif values.get("PROXY_NETWORK"):
        updates["PROXY_NETWORK"] = PROXY_NETWORK_HOST
    if updates:
        env_path = ARGS.dir / ".env"
        env_path.write_text(set_env_values(env_path.read_text(), updates))
    if proxy.kind != "caddy-docker":
        if not out([*docker_cmd(), "network", "ls", "-q", "--filter", f"name=^{PROXY_NETWORK_HOST}$"], check=False):
            run([*docker_cmd(), "network", "create", PROXY_NETWORK_HOST], capture=False)
    return front, back


def check_dns() -> None:
    step("DNS")
    ip = public_ip()
    say(f"this server's public IP: {ip or 'unknown'}")
    for domain in (APP_DOMAIN, API_DOMAIN):
        try:
            resolved = sorted({info[4][0] for info in socket.getaddrinfo(domain, 443, socket.AF_INET)})
        except socket.gaierror:
            resolved = []
        state = "ok" if ip and ip in resolved else "MISMATCH"
        say(f"{domain} -> {', '.join(resolved) or 'no record'}  {state}")
        if state != "ok":
            say("  Cloudflare: Type A, this IP, Proxy status DNS only (grey cloud). "
                "Certificates fail until this is right; deploy continues anyway.")


def build_and_start() -> None:
    step("Build images and start the stack (first time 10-20 minutes; do not press Ctrl+C)")
    if compose_stream("up", "-d", "--build", "--remove-orphans") != 0:
        die("docker compose failed; the output above says why (also in pai.log).")


def wait_healthy(front: int, back: int) -> None:
    step("Waiting for the stack")
    ok = wait_for(f"http://127.0.0.1:{back}/health", seconds=300, label="backend /health")
    ok = wait_for(f"http://127.0.0.1:{front}/", seconds=120, label="frontend") and ok
    if not ok:
        compose("ps", capture=False)
        compose("logs", "--tail", "40", "migrate", "backend", "frontend", capture=False, check=False)
        die("The stack is not healthy; see the logs above.")


def install_host_caddy() -> None:
    step("Installing Caddy on the host")
    apt_install("debian-keyring", "debian-archive-keyring", "apt-transport-https", "gnupg")
    key = out(["curl", "-1sLf", "https://dl.cloudsmith.io/public/caddy/stable/gpg.key"])
    sudo(["sh", "-c", "gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg"],
         inp=key, quiet=True)
    lst = out(["curl", "-1sLf", "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt"])
    sudo_write("/etc/apt/sources.list.d/caddy-stable.list", lst + "\n")
    apt_install("caddy")
    sudo(["systemctl", "enable", "--now", "caddy"], capture=False)


def configure_proxy(proxy: Proxy, front: int, back: int) -> None:
    step(f"Reverse proxy: {proxy.kind}")
    if proxy.kind == "none":
        install_host_caddy()
        proxy.kind = "caddy-host"
    if proxy.kind == "caddy-host":
        current = sudo_read(proxy.caddyfile)
        if is_stock_caddyfile(current):
            current = ""                      # Caddy's stock placeholder site
        new = splice_block(current, render_caddy_blocks(f"127.0.0.1:{front}", f"127.0.0.1:{back}"))
        sudo_write(proxy.caddyfile, new)
        sudo(["caddy", "validate", "--config", proxy.caddyfile], capture=False)
        sudo(["systemctl", "reload", "caddy"], capture=False)
    elif proxy.kind == "caddy-docker":
        current = sudo_read(proxy.caddyfile)
        new = splice_block(current, render_caddy_blocks(f"{FRONTEND_ALIAS}:3000", f"{BACKEND_ALIAS}:8000"))
        sudo_write(proxy.caddyfile, new)
        run([*docker_cmd(), "exec", proxy.container, "caddy", "validate", "--config", "/etc/caddy/Caddyfile"],
            capture=False)
        run([*docker_cmd(), "exec", proxy.container, "caddy", "reload", "--config", "/etc/caddy/Caddyfile"],
            capture=False)
    elif proxy.kind == "nginx-host":
        apt_install("certbot", "python3-certbot-nginx")
        for domain, port in ((APP_DOMAIN, front), (API_DOMAIN, back)):
            src = (ARGS.dir / "deploy" / "nginx" / f"{domain}.conf").read_text()
            src = re.sub(r"127\.0\.0\.1:\d+", f"127.0.0.1:{port}", src)
            sudo_write(f"/etc/nginx/sites-available/{domain}.conf", src)
            sudo(["ln", "-sf", f"/etc/nginx/sites-available/{domain}.conf", "/etc/nginx/sites-enabled/"],
                 capture=False)
        sudo(["nginx", "-t"], capture=False)
        sudo(["systemctl", "reload", "nginx"], capture=False)
        email = ARGS.email or input("Email for Let's Encrypt expiry notices: ").strip()
        sudo(["certbot", "--nginx", "-n", "--agree-tos", "--no-eff-email", "-m", email, "--redirect",
              "-d", APP_DOMAIN, "-d", API_DOMAIN], capture=False, check=False)
        sudo(["systemctl", "reload", "nginx"], capture=False)


def verify_live() -> bool:
    step("Live check (certificates can take a minute)")
    ok = wait_for(f"https://{API_DOMAIN}/health", seconds=180, label=f"https://{API_DOMAIN}/health")
    ok = wait_for(f"https://{APP_DOMAIN}/", seconds=120, label=f"https://{APP_DOMAIN}") and ok
    return ok


def ensure_backup_cron() -> None:
    line = f"15 3 * * * cd {ARGS.dir} && python3 pai.py backup >> backups/backup.log 2>&1"
    current = out(["crontab", "-l"], check=False)
    if "pai.py backup" in current:
        return
    run(["crontab", "-"], inp=(current + "\n" if current else "") + line + "\n", quiet=True)
    say("daily backup at 03:15 added to crontab (backups/)")


def cmd_deploy() -> None:
    preflight()
    ensure_base_packages()
    ensure_swap()
    ensure_docker()
    ensure_checkout()
    os.chdir(ARGS.dir)
    values = ensure_env()
    proxy = detect_proxy()
    front, back = ensure_ports(values, proxy)
    check_dns()
    build_and_start()
    wait_healthy(front, back)
    configure_proxy(proxy, front, back)
    live = verify_live()
    ensure_backup_cron()
    step("Done" if live else "Stack is up; the public URLs are not answering yet")
    say(f"app:   https://{APP_DOMAIN}\napi:   https://{API_DOMAIN}/health\n"
        f"dir:   {ARGS.dir}   log: {LOG_PATH}\n"
        f"next:  Firebase console, Authentication, Settings, Authorized domains: add {APP_DOMAIN}.\n"
        f"       python3 pai.py status   any time.")
    if not live:
        say("If DNS was just changed, wait a few minutes and run: python3 pai.py status")


# --------------------------------------------------------------------------- day to day
def require_checkout() -> dict[str, str]:
    if not (ARGS.dir / COMPOSE_FILE).exists():
        die(f"No stack at {ARGS.dir}. Run: python3 pai.py deploy")
    os.chdir(ARGS.dir)
    return parse_env((ARGS.dir / ".env").read_text()) if (ARGS.dir / ".env").exists() else {}


def cmd_update() -> None:
    values = require_checkout()
    step("Backup before update")
    cmd_backup()
    ensure_checkout()
    build_and_start()
    wait_healthy(int(values.get("FRONTEND_PORT") or 3000), int(values.get("BACKEND_PORT") or 8000))
    verify_live()


def cmd_status() -> None:
    values = require_checkout()
    front, back = int(values.get("FRONTEND_PORT") or 3000), int(values.get("BACKEND_PORT") or 8000)
    step("Containers")
    run([*docker_cmd(), "ps", "--format", "table {{.Names}}\t{{.Status}}"], capture=False)
    step("Resources")
    say(f"RAM {mem_gb():.1f} GB (swap {swap_gb():.1f} GB), free disk {disk_free_gb(ARGS.dir):.1f} GB")
    run(["free", "-h"], capture=False, check=False, quiet=True)
    step("Local")
    status, body = http_get(f"http://127.0.0.1:{back}/health")
    say(f"backend :{back}/health  -> {status} {body.strip()}")
    status, _ = http_get(f"http://127.0.0.1:{front}/")
    say(f"frontend :{front}/     -> {status}")
    step("Recent errors (backend, last 30 min)")
    logs = out([*docker_cmd(), "logs", "--since", "30m", f"{PROJECT}-backend-1"], check=False)
    errors = [l for l in logs.splitlines() if re.search(r"error|traceback|exception", l, re.I)]
    say("\n".join(errors[-8:]) if errors else "none")
    step("Live")
    for url in (f"https://{API_DOMAIN}/health", f"https://{APP_DOMAIN}/"):
        status, body = http_get(url)
        say(f"{url} -> {status} {body.strip()[:60]}")
    step("Spend this month")
    compose("exec", "-T", "postgres", "psql", "-U", DB_USER, "-d", DB_NAME, "-c",
            "select scope, calls, round(est_usd::numeric,2) as usd from pai_usage_months "
            "where month = to_char(now() at time zone 'utc','YYYY-MM') order by est_usd desc;",
            capture=False, check=False, quiet=True)


def cmd_logs() -> None:
    require_checkout()
    compose_stream("logs", "-f", "--tail", "100", "backend", "worker")


def cmd_backup() -> Path:
    require_checkout()
    backups = ARGS.dir / "backups"
    backups.mkdir(exist_ok=True)
    target = backups / f"{DB_NAME}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.dump"
    tmp = target.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        proc = subprocess.run([*docker_cmd(), "compose", "-f", COMPOSE_FILE, "exec", "-T", "postgres",
                               "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                               f"--username={DB_USER}", f"--dbname={DB_NAME}"], stdout=fh)
    if proc.returncode != 0 or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        die("pg_dump failed (is postgres running? python3 pai.py status)")
    tmp.chmod(0o600)
    tmp.rename(target)
    say(f"backup written: {target} ({target.stat().st_size // 1024} KB)")
    for old in sorted(backups.glob(f"{DB_NAME}_*.dump"))[:-14]:
        old.unlink()
    return target


def restore_dump(dump: Path) -> None:
    compose("up", "-d", "postgres", capture=False)
    wait_pg()
    compose("stop", "backend", "worker", capture=False, check=False)
    with dump.open("rb") as fh:
        proc = subprocess.run([*docker_cmd(), "compose", "-f", COMPOSE_FILE, "exec", "-T", "postgres",
                               "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
                               f"--username={DB_USER}", f"--dbname={DB_NAME}"], stdin=fh)
    if proc.returncode != 0:
        say("pg_restore reported errors (often harmless 'does not exist' notices); check the output.")
    say(f"restored {dump.name}")


def wait_pg() -> None:
    for _ in range(30):
        if compose("exec", "-T", "postgres", "pg_isready", "-U", DB_USER, check=False, quiet=True).returncode == 0:
            return
        time.sleep(2)
    die("postgres did not become ready")


def cmd_restore() -> None:
    require_checkout()
    dump = Path(ARGS.file).expanduser()
    if not dump.exists():
        die(f"{dump} not found")
    if not confirm(f"Replace the database with {dump.name}? Current data is overwritten.", default=False):
        return
    cmd_backup()
    restore_dump(dump)
    compose("up", "-d", capture=False)


def volume_tar(volume: str, into: Path, name: str, extract: bool = False) -> None:
    """Copy a Docker volume to/from `into/name` using a throwaway alpine."""
    mode = ["sh", "-c", f"cd /data && tar -xf /out/{name}"] if extract else \
        ["sh", "-c", f"cd /data && tar -cf /out/{name} ."]
    run([*docker_cmd(), "run", "--rm", "-v", f"{volume}:/data", "-v", f"{into}:/out", "alpine", *mode],
        capture=False)


def cmd_export() -> None:
    require_checkout()
    target = Path(ARGS.out).expanduser() if ARGS.out else \
        ARGS.dir / "backups" / f"pai-export_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.tar.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pai-export-") as tmp_s:
        tmp = Path(tmp_s)
        os.chmod(tmp, 0o755)
        shutil.copy(cmd_backup(), tmp / "db.dump")
        for volume in ("files", "qdrant_data"):
            volume_tar(f"{PROJECT}_{volume}", tmp, f"{volume}.tar")
        with tarfile.open(target, "w:gz") as tar:
            tar.add(tmp / "db.dump", "db.dump")
            for volume in ("files", "qdrant_data"):
                tar.add(tmp / f"{volume}.tar", f"{volume}.tar")
            for rel in (".env", "secrets", "proposals"):
                if (ARGS.dir / rel).exists():
                    tar.add(ARGS.dir / rel, rel)
    target.chmod(0o600)
    say(f"export written: {target} ({target.stat().st_size // 1024 // 1024} MB)")
    say(f"On the new server:  python3 pai.py import {target.name}   then   python3 pai.py deploy")


def cmd_import() -> None:
    bundle = Path(ARGS.file).expanduser()
    if not bundle.exists():
        die(f"{bundle} not found")
    if not (ARGS.dir / COMPOSE_FILE).exists():
        ensure_base_packages()
        ensure_docker()
        ensure_checkout()
    os.chdir(ARGS.dir)
    if (ARGS.dir / ".env").exists() and not confirm("A stack already exists here. Overwrite its data with the import?", default=False):
        return
    compose("down", capture=False, check=False)
    with tempfile.TemporaryDirectory(prefix="pai-import-") as tmp_s:
        tmp = Path(tmp_s)
        os.chmod(tmp, 0o755)
        with tarfile.open(bundle) as tar:
            tar.extractall(tmp, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(tmp)
        for rel in (".env", "secrets", "proposals"):
            src = tmp / rel
            if src.exists():
                dst = ARGS.dir / rel
                if dst.is_dir():
                    shutil.rmtree(dst)
                elif dst.exists():
                    dst.unlink()
                shutil.move(str(src), str(dst))
        os.chmod(ARGS.dir / ".env", 0o600)
        env_text = (ARGS.dir / ".env").read_text()      # ports/proxy are re-decided by deploy
        env_text = re.sub(r"^\s*PROXY_NETWORK\s*=.*\n?", "", env_text, flags=re.M)
        (ARGS.dir / ".env").write_text(env_text)
        for volume in ("files", "qdrant_data"):
            if (tmp / f"{volume}.tar").exists():
                run([*docker_cmd(), "volume", "create", f"{PROJECT}_{volume}"], quiet=True)
                volume_tar(f"{PROJECT}_{volume}", tmp, f"{volume}.tar", extract=True)
        run([*docker_cmd(), "volume", "create", f"{PROJECT}_pgdata"], quiet=True)
        restore_dump(tmp / "db.dump")
    say("import done. Now run:  python3 pai.py deploy")


def cmd_migrate_from() -> None:
    host, _, remote_dir = ARGS.source.partition(":")
    remote_dir = remote_dir or "~/pai-c"
    step(f"Exporting on {host} ({remote_dir})")
    remote_out = "/tmp/pai-export.tar.gz"
    if run(["ssh", host, f"cd {remote_dir} && python3 pai.py export --out {remote_out}"],
           capture=False, check=False).returncode != 0:
        # old checkout without pai.py: send this file over first
        run(["scp", str(Path(__file__).resolve()), f"{host}:{remote_dir}/pai.py"], capture=False)
        run(["ssh", host, f"cd {remote_dir} && python3 pai.py export --out {remote_out}"], capture=False)
    local = Path.home() / "pai-export.tar.gz"
    run(["scp", f"{host}:{remote_out}", str(local)], capture=False)
    run(["ssh", host, f"rm -f {remote_out}"], capture=False, check=False)
    ARGS.file = str(local)
    cmd_import()
    cmd_deploy()


def cmd_env() -> None:
    require_checkout()
    updates = {}
    for pair in ARGS.pairs:
        key, sep, value = pair.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            die(f"expected KEY=VALUE, got {pair!r}")
        updates[key] = value
    env_path = ARGS.dir / ".env"
    env_path.write_text(set_env_values(env_path.read_text(), updates))
    say("set " + ", ".join(updates))
    compose("up", "-d", "backend", "worker", capture=False)


def cmd_restart() -> None:
    require_checkout()
    compose("restart", "backend", "worker", "frontend", capture=False)


def cmd_stop() -> None:
    require_checkout()
    compose("stop", capture=False)


def cmd_start() -> None:
    values = require_checkout()
    compose("up", "-d", capture=False)
    wait_healthy(int(values.get("FRONTEND_PORT") or 3000), int(values.get("BACKEND_PORT") or 8000))


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> None:
    global ARGS, LOG_PATH
    parser = argparse.ArgumentParser(prog="pai.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=None, help=f"stack folder (default {DEFAULT_DIR})")
    parser.add_argument("--repo", default=REPO_URL)
    parser.add_argument("--branch", default=REPO_BRANCH)
    parser.add_argument("--env-file", help="deploy: use this .env instead of asking")
    parser.add_argument("--firebase-json", help="deploy: path to the service-account JSON")
    parser.add_argument("--email", help="nginx only: Let's Encrypt contact email")
    parser.add_argument("--yes", "-y", action="store_true", help="never ask (fails on missing secrets)")
    parser.add_argument("--force", action="store_true", help="ignore the RAM check")
    parser.add_argument("--no-pull", action="store_true", help="deploy: do not git pull")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("deploy", "update", "status", "logs", "backup", "restart", "stop", "start"):
        sub.add_parser(name)
    sub.add_parser("restore").add_argument("file")
    sub.add_parser("export").add_argument("--out")
    sub.add_parser("import").add_argument("file")
    sub.add_parser("migrate-from").add_argument("source", help="user@oldhost[:dir]")
    sub.add_parser("env").add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    ARGS = parser.parse_args(argv)
    here = Path(__file__).resolve().parent
    ARGS.dir = (ARGS.dir or (here if (here / COMPOSE_FILE).exists() else DEFAULT_DIR)).expanduser().resolve()
    if ARGS.dir.exists():
        LOG_PATH = ARGS.dir / "pai.log"
    handlers = {
        "deploy": cmd_deploy, "update": cmd_update, "status": cmd_status, "logs": cmd_logs,
        "backup": cmd_backup, "restore": cmd_restore, "export": cmd_export, "import": cmd_import,
        "migrate-from": cmd_migrate_from, "env": cmd_env, "restart": cmd_restart,
        "stop": cmd_stop, "start": cmd_start,
    }
    try:
        handlers[ARGS.command]()
    except subprocess.CalledProcessError as exc:
        die(f"command failed ({exc.returncode}): {' '.join(exc.cmd)}\n{(exc.stdout or '')[-2000:]}")
    except KeyboardInterrupt:
        die("interrupted", 130)


if __name__ == "__main__":
    main()
