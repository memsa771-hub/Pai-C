"""Beta smoke: one fresh student through the running local stack, real models.

Drives the HTTP API the frontend uses (BETA_CONVERSATION_SPEC 6): sign-up,
onboarding, the opening, six chat turns, Vault, Mirror, paths, roadmap
(choose and tick), "how does PAI work?", and the month's spend after every
model-bound step. Each step is a named check with pass/fail and timing; the
run stops at the first hard failure (or when the spend this run caused goes
over --cap-usd) and always writes the report.

Authentication (the backend accepts only Firebase ID tokens):
  --create-student   make a fresh Firebase account with the Admin SDK (the
                     service account in secrets/ or FIREBASE_SERVICE_ACCOUNT)
                     and sign it in with the web API key from .env
                     (NEXT_PUBLIC_FIREBASE_API_KEY). No browser needed.
  --token ID_TOKEN   an ID token of an account that signed up in the browser
                     and has NOT done onboarding: sign up on
                     http://localhost:3000, stop at the onboarding form, then
                     DevTools > Network > any request to localhost:8000/v1 >
                     Request Headers > "Authorization: Bearer <token>" (copy
                     <token>). It expires in an hour.

Spend (one is required; the spend is the month counter's growth during the run):
  --founder-token T  GET /v1/admin/usage with a founder's ID token
  --spend-from-docker  read cap_state() inside the running backend container
  --spend-from-db    read cap_state() in this process (DATABASE_URL must reach
                     the database; the compose Postgres is not published)

Usage, from backend/:
  python -m scripts.beta_smoke --dry-run --create-student --spend-from-docker
  python -m scripts.beta_smoke --create-student --spend-from-docker --cap-usd 5 \
      --language roman_ur --report ../docs/counselor/BETA_SMOKE_REPORT.md

--dry-run makes no model call: it checks the backend is up, the credentials
work, the spend source reads and the models resolve. With --create-student it
also creates the Firebase account and workspace and stops before onboarding
(onboarding queues the opening, a model call); without, it only checks that the
service account and web key are present.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
POLICY = ROOT / "app" / "pai_c" / "policy"
CHANNEL = "pai-counselor"
ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
RAW_CODE = re.compile(r"\b[a-z]+_[a-z_]+\b")
ROMAN_UR_WORDS = {"aap", "ap", "hai", "hain", "kya", "ke", "ki", "ka", "mein", "ko", "se", "nahi", "aur",
                  "kaise", "apne", "apka", "aapka", "tum", "yeh", "ye", "bhi", "kar", "karna", "hota"}
EDUCATION_WORDS = ("pre-engineering", "pre engineering", "pre‑engineering")
STUDENT_LEVELS = {"inferred", "stated", "shown", "confirmed"}

ONBOARDING = {"firstName": "Ali", "lastName": "Raza", "level": "intermediate", "group": "pre_engineering",
              "status": "current", "year": "year_2", "dateOfBirth": "2008-05-14", "gender": "male",
              "currentCountry": "Pakistan", "currentCity": "Lahore"}

TURNS = {
    "roman_ur": [
        "Mujhe robots banana pasand hai, farigh waqt mein main chhote robot aur gadgets banata hun.",
        "First year mein mere 78% marks aaye thay, Lahore board se.",
        "Mere abbu chahte hain ke main MBBS karun, lekin mujhe biology itni pasand nahi.",
        "Hamara budget saal ka 3 se 6 lakh rupay tak hai.",
        "Main Lahore se bahar nahi ja sakta, ghar walay ijazat nahi dete.",
        "Mujhe circuits jorna aur electronics ke saath kaam karna sab se acha lagta hai.",
    ],
    "en": [
        "In my free time I like building small robots and gadgets.",
        "I got 78% in first year, from the Lahore board.",
        "My father wants me to do MBBS, but I don't really like biology.",
        "Our budget is 3 to 6 lakh rupees a year.",
        "I can't leave Lahore, my family won't allow it.",
        "What I enjoy most is wiring circuits and working with electronics.",
    ],
}
ABOUT = {"roman_ur": "PAI kaise kaam karti hai?", "en": "How does PAI work?"}

PROBE = r'''
import json
from app.inference import gateway, usage
state = usage.cap_state()
by_role = {}
try:
    for scope, calls, usd in usage.month_rows(state["month"]):
        role = scope.split(":", 1)[1] if scope.startswith(usage.MODELS_SCOPE + ":") else scope
        by_role[role] = round(usd, 6)
except Exception:
    pass
roles = {}
for role in gateway.model_roles()["roles"]:
    try:
        cfg = gateway.resolve_role(role)
        roles[role] = {"provider": cfg.provider, "model": cfg.model}
    except Exception as exc:
        roles[role] = {"provider": "?", "model": "unresolved: " + type(exc).__name__}
print("BETA_SMOKE_PROBE " + json.dumps({"spent": state["spent"], "cap": state["cap"], "stage": state["stage"],
                                        "month": state["month"], "by_role": by_role, "roles": roles}))
'''


# ---- pure checks (tested offline) ------------------------------------------

def praise_words() -> list[str]:
    """The banned praise list the Mirror text job uses (policy/mirror.json)."""
    return json.loads((POLICY / "mirror.json").read_text(encoding="utf-8"))["text"]["praise_words"]


def about_words() -> list[str]:
    """The feature names the "how does PAI work" answer is drawn from."""
    return list(json.loads((POLICY / "about_pai.json").read_text(encoding="utf-8"))["features"])


def question_count(text: str) -> int:
    return sum("QUESTION MARK" in unicodedata.name(ch, "") for ch in text)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.casefold()))


def check_language(text: str, language: str) -> tuple[bool, str]:
    """Latin script for both sets (Arabic script for an Urdu-script set);
    a Roman Urdu reply uses Roman Urdu words, an English reply does not."""
    if language == "ur":
        return (bool(ARABIC.search(text)), "Urdu script" if ARABIC.search(text) else "no Urdu script")
    if ARABIC.search(text):
        return False, "Arabic script in a Latin-script conversation"
    hits = _words(text) & ROMAN_UR_WORDS
    if language == "roman_ur" and len(hits) < 2:
        return False, f"does not read as Roman Urdu (markers {sorted(hits)})"
    if language == "en" and len(hits - {"ke", "ka", "ki", "se", "ko", "ye", "ap"}) >= 2:
        return False, f"Roman Urdu words in an English reply {sorted(hits)}"
    return True, ""


def check_reply(text: str, metadata: dict | None, language: str, banned: list[str]) -> tuple[bool, str]:
    """One question (or a next_step), no praise, the student's language."""
    problems = []
    questions = question_count(text)
    step = (metadata or {}).get("next_step")
    if not (questions == 1 or (questions == 0 and step)):
        problems.append(f"{questions} questions" + ("" if step else ", no next_step"))
    lowered = text.casefold()
    praised = [w for w in banned if re.search(rf"(?<![\w]){re.escape(w.casefold())}(?![\w])", lowered)]
    if praised:
        problems.append(f"praise {praised}")
    ok, why = check_language(text, language)
    if not ok:
        problems.append(why)
    return not problems, "; ".join(problems)


def check_opening(text: str, labels: list[str]) -> tuple[bool, str]:
    lowered = text.casefold()
    named = any(w.casefold() in lowered for w in (*EDUCATION_WORDS, *labels) if w)
    stripped = text.rstrip()
    one_question = question_count(text) == 1 and stripped[-1:] in ("?", "؟")
    problems = ([] if named else ["does not name Pre-Engineering"]) + \
               ([] if one_question else [f"{question_count(text)} questions / does not end with one"])
    return not problems, "; ".join(problems)


def vault_entries(vault: dict) -> list[dict]:
    entries = [e for section in (vault.get("details") or {}).values() for e in section.get("entries", [])]
    return entries + [e for card in vault.get("story") or [] for e in card.get("entries", [])]


def check_vault(vault: dict) -> tuple[bool, str]:
    entries = vault_entries(vault)
    problems = []
    if len(entries) < 8:
        problems.append(f"{len(entries)} entries (< 8)")
    unbadged = [e.get("type") for e in entries if not e.get("badge")]
    if unbadged:
        problems.append(f"no badge: {unbadged}")
    raw = [e.get("display") for e in entries if RAW_CODE.search(e.get("display") or "")]
    if raw:
        problems.append(f"raw codes: {raw}")
    known = (vault.get("completeness") or {}).get("known", 0)
    if known < 5:
        problems.append(f"completeness.known {known} (< 5)")
    return not problems, "; ".join(problems) or f"{len(entries)} entries, known {known}"


def mirror_text(card: dict) -> str:
    text = card.get("text") or {}
    return " ".join(text.get("sentences") or []) if isinstance(text, dict) else str(text)


def check_mirror(card: dict, earlier_version: str | None = None) -> tuple[bool, str]:
    problems = []
    if not card.get("ready"):
        problems.append("not ready")
    if not mirror_text(card).strip():
        problems.append("no text")
    filled = [a["key"] for a in card.get("areas") or [] if a.get("entries")]
    if not filled:
        problems.append("no area has entries")
    if not isinstance(card.get("unknowns"), list):
        problems.append("no unknowns list")
    if earlier_version is not None and card.get("version") == earlier_version:
        problems.append("not redrawn since onboarding")
    note = f"areas with entries {filled}, unknowns {len(card.get('unknowns') or [])}"
    return not problems, "; ".join(problems + [note]) if problems else note


def check_paths(possibilities: list[dict]) -> tuple[bool, str]:
    paths = [p for p in possibilities if p.get("status") != "dismissed"]
    if not paths:
        return False, "no paths"
    problems, notes = [], 0
    for path in paths:
        evidence = path.get("evidence") or []
        cited = [e for e in evidence if e.get("evidence_level") in STUDENT_LEVELS]
        notes += sum(e.get("evidence_level") == "source" for e in evidence)
        if not (path.get("why") or "").strip() or not cited:
            problems.append(f"{path.get('title')}: why without Vault evidence")
    tail = f"{len(paths)} paths; field notes cited: {notes}" + ("" if notes else " (absent)")
    return not problems, "; ".join(problems + [tail])


def check_roadmap(page: dict, region: str = "punjab") -> tuple[bool, str]:
    cards = page.get("fields") or []
    problems = []
    if not cards:
        return False, "no fields"
    uncoloured = [c.get("title") for c in cards for s in c.get("steps") or [] if not s.get("colour")]
    if uncoloured:
        problems.append(f"steps without colour on {sorted(set(uncoloured))}")
    if not page.get("rules_as_of"):
        problems.append("no rules_as_of")
    timed = [c for c in cards if c.get("time")]
    regions = {b.get("region") for c in timed for b in c["time"].get("basis") or []}
    if region not in regions:
        problems.append(f"time.basis regions {sorted(r for r in regions if r)} lack {region}")
    note = f"{len(cards)} fields, {len(timed)} timed, statuses {[c.get('status') for c in cards]}"
    return not problems, "; ".join(problems + [note]) if problems else note


def check_about(text: str, words: list[str]) -> tuple[bool, str]:
    named = [w for w in words if w.casefold() in text.casefold()]
    return bool(named), f"names {named}" if named else "names none of " + ", ".join(words)


# ---- run state and report ---------------------------------------------------

@dataclass
class Check:
    name: str
    ok: bool
    ms: int
    note: str = ""
    hard: bool = False


@dataclass
class Run:
    language: str
    base_url: str
    cap_usd: float
    dry_run: bool = False
    checks: list[Check] = field(default_factory=list)
    transcript: list[tuple[str, str]] = field(default_factory=list)
    student: dict = field(default_factory=dict)
    spend: dict = field(default_factory=dict)
    roles: dict = field(default_factory=dict)
    stopped: str | None = None

    @property
    def passed(self) -> bool:
        return self.stopped is None and all(c.ok for c in self.checks)


class HardFailure(Exception):
    pass


class CapReached(HardFailure):
    pass


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_report(run: Run, path: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Beta smoke report ({now})", "",
             f"- Base URL: {run.base_url}", f"- Language: {run.language}",
             f"- Mode: {'dry run (no model calls)' if run.dry_run else 'live, real models'}",
             f"- Cap: ${run.cap_usd:.2f}",
             f"- Student: {run.student.get('email', '-')} workspace {run.student.get('workspace_id', '-')}",
             f"- Result: {'PASS' if run.passed else 'FAIL'}"
             + (f" (stopped: {run.stopped})" if run.stopped else ""), "",
             "## Checks", "", "| # | Check | Result | ms | Note |", "| --- | --- | --- | --- | --- |"]
    for i, c in enumerate(run.checks, 1):
        lines.append(f"| {i} | {_cell(c.name)} | {'pass' if c.ok else 'FAIL'} | {c.ms} | {_cell(c.note)} |")
    lines += ["", "## Spend", ""]
    if run.spend:
        s = run.spend
        lines.append(f"- Source: {s.get('source')}; month {s.get('month', '-')}, stage {s.get('stage', '-')}")
        if s.get("baseline") is not None and s.get("final") is not None:
            lines.append(f"- Month counter: ${s['baseline']:.4f} before, ${s['final']:.4f} after; "
                         f"this run est_usd **${s['final'] - s['baseline']:.4f}**")
        for role, usd in sorted((s.get("by_role_delta") or {}).items(), key=lambda kv: -kv[1]):
            lines.append(f"  - {role}: ${usd:.4f}")
    else:
        lines.append("- not read")
    lines += ["", "## Models per role (as resolved)", ""]
    if run.roles:
        lines += ["| Role | Provider | Model |", "| --- | --- | --- |"]
        lines += [f"| {r} | {v.get('provider')} | {v.get('model')} |" for r, v in sorted(run.roles.items())]
    else:
        lines.append("- not resolved")
    defects = [c for c in run.checks if not c.ok]
    lines += ["", "## Defects", ""]
    lines += [f"- {c.name}: {c.note}" for c in defects] or ["- none"]
    if run.transcript:
        lines += ["", "## Transcript", ""]
        lines += [f"**{who}:** {_cell(text)}" + "  " for who, text in run.transcript]
    report = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return report


# ---- spend sources ----------------------------------------------------------

def _parse_probe(output: str) -> dict:
    for line in output.splitlines():
        if line.startswith("BETA_SMOKE_PROBE "):
            return json.loads(line[len("BETA_SMOKE_PROBE "):])
    raise RuntimeError("probe printed no result: " + output[-400:])


def probe_docker() -> dict:
    done = subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "-c", PROBE],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError(f"docker probe failed: {done.stderr[-400:]}")
    return _parse_probe(done.stdout)


def probe_local() -> dict:
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError(f"local probe failed: {done.stderr[-400:]}")
    return _parse_probe(done.stdout)


class Spend:
    """The month counter, read before the run and after every model-bound step;
    the run's spend is its growth (other traffic on the stack counts too)."""

    def __init__(self, read, cap_usd: float, source: str):
        self.read, self.cap, self.source = read, cap_usd, source
        self.baseline = self.last = None
        self.state: dict = {}

    def start(self) -> dict:
        self.state = self.read()
        if self.state.get("spent") is None:
            raise HardFailure("spend counter unreadable")
        self.baseline = self.last = float(self.state["spent"])
        self.base_roles = dict(self.state.get("by_role") or {})
        return self.state

    def check(self) -> float:
        self.state = self.read()
        self.last = float(self.state.get("spent") or self.last or 0.0)
        used = self.last - self.baseline
        if used > self.cap:
            raise CapReached(f"spent ${used:.4f} > cap ${self.cap:.2f}")
        return used

    def summary(self) -> dict:
        roles = self.state.get("by_role") or {}
        delta = {r: round(u - self.base_roles.get(r, 0.0), 6) for r, u in roles.items()
                 if u - self.base_roles.get(r, 0.0) > 0}
        return {"source": self.source, "month": self.state.get("month"), "stage": self.state.get("stage"),
                "baseline": self.baseline, "final": self.last, "by_role_delta": delta}


# ---- HTTP ------------------------------------------------------------------

class Api:
    def __init__(self, base_url: str, bearer: str | None = None, http=None):
        import httpx
        self.http = http or httpx.Client(base_url=base_url, timeout=60)
        self.bearer, self.token, self.workspace_id = bearer, None, None

    def call(self, method: str, path: str, *, params=None, body=None, bearer: str | None = None):
        headers = {}
        if bearer or self.bearer:
            headers["Authorization"] = f"Bearer {bearer or self.bearer}"
        if self.token:
            headers["X-Workspace-Token"] = self.token
        if self.workspace_id and path.startswith(("/v1/vault", "/v1/counselor", "/v1/roadmap")):
            params = {"network": self.workspace_id, **(params or {})}
        response = self.http.request(method, path, params=params, json=body, headers=headers)
        try:
            data = response.json()
        except ValueError:
            data = {"detail": response.text[:300]}
        if response.status_code >= 400 or (isinstance(data, dict) and data.get("code") not in (None, 0)):
            raise HardFailure(f"{method} {path}: {response.status_code} "
                              f"{data.get('message') or data.get('detail') if isinstance(data, dict) else data}")
        return data.get("data") if isinstance(data, dict) and "code" in data else data


def _env():
    import app.config  # noqa: F401  (loads ../.env into os.environ)


def service_account_path() -> Path | None:
    _env()
    named = os.environ.get("FIREBASE_SERVICE_ACCOUNT") or os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE")
    for candidate in ([Path(named), REPO / named] if named else []) + [REPO / "secrets" / "firebase-service-account.json"]:
        if candidate.is_file():
            return candidate
    return None


def web_api_key() -> str:
    _env()
    return (os.environ.get("FIREBASE_WEB_API_KEY") or os.environ.get("NEXT_PUBLIC_FIREBASE_API_KEY") or "").strip()


def create_firebase_student(email: str, name: str) -> str:
    """A verified Firebase account and a fresh ID token for it (custom-token sign-in)."""
    import firebase_admin
    import httpx
    from firebase_admin import auth, credentials
    path, key = service_account_path(), web_api_key()
    if path is None or not key:
        raise HardFailure("--create-student needs the service account and NEXT_PUBLIC_FIREBASE_API_KEY")
    try:
        app = firebase_admin.get_app("beta-smoke")
    except ValueError:
        app = firebase_admin.initialize_app(credentials.Certificate(str(path)), name="beta-smoke")
    user = auth.create_user(email=email, email_verified=True, display_name=name,
                            password=secrets.token_urlsafe(18), app=app)
    custom = auth.create_custom_token(user.uid, app=app)
    response = httpx.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={key}",
                          json={"token": custom.decode() if isinstance(custom, bytes) else custom,
                                "returnSecureToken": True}, timeout=30)
    if response.status_code != 200:
        raise HardFailure(f"signInWithCustomToken: {response.status_code} {response.text[:200]}")
    return response.json()["idToken"]


# ---- the run ----------------------------------------------------------------

class Smoke:
    def __init__(self, run: Run, api: Api, spend: Spend | None, *, sleep=time.sleep, clock=time.monotonic,
                 reply_timeout: float = 120.0):
        self.run, self.api, self.spend = run, api, spend
        self.sleep, self.clock, self.reply_timeout = sleep, clock, reply_timeout
        self.cursor = None
        self.banned, self.about = praise_words(), about_words()

    def step(self, name: str, fn, *, hard: bool = False, model: bool = False):
        """Run one check; fn returns (ok, note). A hard check that fails, any
        exception, or the cap stops the run."""
        started = self.clock()
        try:
            ok, note = fn()
        except HardFailure as exc:
            ok, note, hard = False, str(exc), True
        except Exception as exc:  # a broken step must still leave a report
            ok, note, hard = False, f"{type(exc).__name__}: {exc}", True
        self.run.checks.append(Check(name, ok, int((self.clock() - started) * 1000), note, hard))
        if model and self.spend is not None:
            spend_started = self.clock()
            try:
                used = self.spend.check()
                self.run.checks[-1].note += f" [spend ${used:.4f}]"
            except CapReached as exc:
                self.run.checks.append(Check("spend cap", False, int((self.clock() - spend_started) * 1000),
                                             str(exc), True))
                raise
        if not ok and hard:
            raise HardFailure(f"{name}: {note}")
        return ok

    # -- messages --

    def _events(self, after=None, sort="asc", limit=100):
        params = {"network": self.api.workspace_id, "channel": CHANNEL, "type": "workspace.message",
                  "sort": sort, "limit": limit, "exclude_message_types": "thinking,status,todos"}
        if after:
            params["after"] = after
        return self.api.call("GET", "/v1/events", params=params) or {}

    def mark(self):
        self.cursor = (self._events(sort="desc", limit=1) or {}).get("newest_id")

    def wait_reply(self, timeout: float | None = None) -> dict:
        """The next PAI chat message after the cursor; advances the cursor."""
        deadline = self.clock() + (timeout or self.reply_timeout)
        while self.clock() < deadline:
            data = self._events(after=self.cursor)
            for event in data.get("events") or []:
                self.cursor = event["id"]
                payload = event.get("payload") or {}
                if str(event.get("source") or "").startswith("human:"):
                    continue
                if payload.get("message_type", "chat") == "chat" and (payload.get("content") or "").strip():
                    self.run.transcript.append(("PAI", payload["content"]))
                    return event
            self.sleep(2)
        raise HardFailure(f"no PAI reply within {int(timeout or self.reply_timeout)} s")

    def say(self, text: str) -> dict:
        posted = self.api.call("POST", "/v1/events", body={
            "network": self.api.workspace_id, "type": "workspace.message.posted",
            "target": f"channel/{CHANNEL}", "visibility": "channel",
            "payload": {"content": text, "sender_type": "human", "sender_name": ONBOARDING["firstName"]}})
        self.run.transcript.append(("Student", text))
        if posted and posted.get("id"):
            self.cursor = posted["id"]
        return self.wait_reply()

    def poll(self, fetch, done, timeout: float):
        deadline = self.clock() + timeout
        value = fetch()
        while not done(value) and self.clock() < deadline:
            self.sleep(5)
            value = fetch()
        return value

    # -- steps --

    def sign_in(self, args) -> None:
        def go():
            if args.create_student:
                email = f"beta-smoke-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{secrets.token_hex(2)}@example.com"
                self.api.bearer = create_firebase_student(email, f"{ONBOARDING['firstName']} {ONBOARDING['lastName']}")
                self.run.student["email"] = email
            session = self.api.call("POST", "/v1/auth/session", body={"deviceId": "beta-smoke-" + secrets.token_hex(6)})
            created = self.api.call("POST", "/v1/workspaces", body={"name": "Beta smoke"})
            self.api.workspace_id, self.api.token = created["workspaceId"], created["token"]
            self.run.student.setdefault("email", (session.get("user") or {}).get("email"))
            self.run.student["workspace_id"] = self.api.workspace_id
            state = self.api.call("GET", "/v1/vault/onboarding")
            self.labels = [label for f in state.get("fields") or [] if f.get("name") == "group"
                           for code, label in (f.get("labels") or {}).items() if code == "pre_engineering"]
            if not state.get("required"):
                return False, "onboarding already done: not a fresh student"
            return True, f"workspace {self.api.workspace_id}"
        self.step("1 sign-in, fresh student", go, hard=True)

    def onboarding(self) -> None:
        def go():
            self.mark()
            self.earlier = self.api.call("GET", "/v1/counselor/summary")["card"].get("version")
            result = self.api.call("POST", "/v1/vault/onboarding", body={"answers": ONBOARDING})
            ok = bool(result.get("completed")) and not result.get("rejected")
            return ok, f"saved {result.get('saved')}, rejected {result.get('rejected')}"
        self.step("2 onboarding", go, hard=True)

    def opening(self) -> None:
        def go():
            event = self.wait_reply(60)
            return check_opening(event["payload"]["content"], getattr(self, "labels", []))
        self.step("3 opening names education, one question", go, model=True)

    def chat(self) -> None:
        for i, text in enumerate(TURNS[self.run.language], 1):
            def go(text=text):
                event = self.say(text)
                return check_reply(event["payload"]["content"], event.get("metadata"), self.run.language, self.banned)
            self.step(f"4.{i} turn: {text[:40]}", go, model=True)

    def vault(self) -> None:
        self.step("5 vault", lambda: check_vault(self.api.call("GET", "/v1/vault")))

    def mirror(self) -> None:
        def go():
            card = self.poll(lambda: self.api.call("GET", "/v1/counselor/summary")["card"],
                             lambda c: c.get("ready") and mirror_text(c).strip(), 90)
            return check_mirror(card, getattr(self, "earlier", None))
        self.step("6 mirror ready, text, redrawn", go, model=True)

    def paths(self) -> None:
        def go():
            rows = self.poll(lambda: self.api.call("GET", "/v1/counselor/possibilities")["possibilities"],
                             lambda r: any(p.get("status") != "dismissed" for p in r), 120)
            ok, note = check_paths(rows)
            if not rows:
                analysis = self.api.call("GET", "/v1/counselor/possibilities/analysis")
                note += f"; analysis {analysis}"
            return ok, note
        self.step("7 paths with Vault-cited reasons", go, model=True)
        if self.run.checks[-1].note.startswith("no paths"):
            raise HardFailure("7 paths: no paths, nothing to choose")

    def roadmap(self) -> None:
        page = {}

        def view():
            page.update(self.api.call("GET", "/v1/roadmap"))
            return check_roadmap(page)
        self.step("8a roadmap steps coloured, region dates", view)
        card = next((c for c in page.get("fields") or [] if c.get("status") in ("open", "step")), None)

        def choose():
            if card is None:
                return False, "no open/step field to choose"
            self.api.call("POST", "/v1/roadmap/choose", body={"field_key": card["field_key"]})
            stage = self.api.call("GET", "/v1/counselor/workspace").get("stage")
            return stage == "CHOSEN", f"chose {card['field_key']}; stage {stage}"
        if not self.step("8b choose -> CHOSEN", choose):
            return

        def tick():
            chosen = self.api.call("GET", "/v1/roadmap").get("chosen") or {}
            step = next((s for s in chosen.get("steps") or [] if s.get("kind") == "apply"), None)
            if step is None:
                return False, "no apply step on the chosen route"
            if not step.get("tickable"):
                return False, f"apply step not tickable (status {step.get('status')})"
            result = self.api.call("POST", "/v1/roadmap/steps", body={"key": step["key"], "done": True})
            return step["key"] in (result.get("steps_done") or []), f"steps_done {result.get('steps_done')}"
        self.step("8c tick apply step", tick)

    def about_pai(self) -> None:
        def go():
            text = self.say(ABOUT[self.run.language])["payload"]["content"]
            ok, note = check_about(text, self.about)
            lang_ok, why = check_language(text, self.run.language)
            return ok and lang_ok, "; ".join(x for x in (note, why) if x)
        self.step("9 how does PAI work", go, model=True)

    def live(self, args) -> None:
        self.sign_in(args)
        self.onboarding()
        self.opening()
        self.chat()
        self.vault()
        self.mirror()
        self.paths()
        self.roadmap()
        self.about_pai()

    def dry(self, args) -> None:
        def health():
            self.api.call("GET", "/health")
            return True, "backend up"
        self.step("health", health, hard=True)

        if args.create_student:  # makes a real Firebase account and workspace; still no model call
            self.sign_in(args)
            return

        def credentials():
            if args.token:
                created = self.api.call("POST", "/v1/workspaces", body={"name": "Beta smoke"})
                self.api.workspace_id, self.api.token = created["workspaceId"], created["token"]
                state = self.api.call("GET", "/v1/vault/onboarding")
                return bool(state.get("required")), f"token works; onboarding required {state.get('required')}"
            import firebase_admin  # noqa: F401
            path, key = service_account_path(), web_api_key()
            return bool(path and key), f"service account {'found' if path else 'missing'}, web key " \
                                       f"{'set' if key else 'missing'} (no account created in a dry run)"
        self.step("credentials", credentials)


def run_smoke(args, *, api=None, spend=None, sleep=time.sleep, clock=time.monotonic) -> Run:
    run = Run(args.language, args.base_url, args.cap_usd, dry_run=args.dry_run)
    api = api or Api(args.base_url, args.token)
    smoke = Smoke(run, api, spend, sleep=sleep, clock=clock, reply_timeout=args.reply_timeout)
    try:
        if spend is not None:
            smoke.step("spend baseline", lambda: (True, f"month ${spend.start()['spent']:.4f}"), hard=True)
            run.roles = spend.state.get("roles") or {}
        smoke.dry(args) if args.dry_run else smoke.live(args)
    except HardFailure as exc:
        run.stopped = str(exc)
    finally:
        if spend is not None and spend.baseline is not None:
            try:
                spend.check()
            except Exception:  # the report is written either way; a cap stop is already recorded
                pass
            run.spend = spend.summary()
    return run


def make_spend(args) -> Spend | None:
    if args.founder_token:
        def read():
            api = Api(args.base_url)
            data = api.call("GET", "/v1/admin/usage", bearer=args.founder_token)
            return {**data, "by_role": {r["role"]: r["est_usd"] for r in data.get("by_role") or []},
                    "roles": probe_local().get("roles")}
        return Spend(read, args.cap_usd, "GET /v1/admin/usage (roles from local .env)")
    if args.spend_from_docker:
        return Spend(probe_docker, args.cap_usd, "cap_state() in the backend container")
    if args.spend_from_db:
        return Spend(probe_local, args.cap_usd, "cap_state() in this process")
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cap-usd", type=float, default=5.0, help="stop when this run's spend passes it")
    parser.add_argument("--language", choices=sorted(TURNS), default="roman_ur")
    parser.add_argument("--report", default=str(REPO / "docs" / "counselor" / "BETA_SMOKE_REPORT.md"))
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--create-student", action="store_true", help="make a fresh Firebase account (Admin SDK)")
    who.add_argument("--token", help="Firebase ID token of a fresh browser sign-up")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--founder-token", help="founder's Firebase ID token for /v1/admin/usage")
    source.add_argument("--spend-from-docker", action="store_true")
    source.add_argument("--spend-from-db", action="store_true")
    parser.add_argument("--reply-timeout", type=float, default=120.0, help="seconds to wait for each reply")
    parser.add_argument("--dry-run", action="store_true", help="no model calls: check stack, auth, spend, models")
    args = parser.parse_args(argv)
    if not args.dry_run:
        if not (args.create_student or args.token):
            parser.error("pass --create-student or --token")
        if not (args.founder_token or args.spend_from_docker or args.spend_from_db):
            parser.error("a live run needs a spend source: --founder-token, --spend-from-docker or --spend-from-db")
        if not args.cap_usd > 0:
            parser.error("--cap-usd must be greater than zero")
    run = run_smoke(args, spend=make_spend(args))
    report_path = Path(args.report)
    write_report(run, report_path)
    for c in run.checks:
        print(f"{'PASS' if c.ok else 'FAIL'} {c.name} ({c.ms} ms) {c.note}")
    if run.spend.get("final") is not None and run.spend.get("baseline") is not None:
        print(f"est_usd this run: ${run.spend['final'] - run.spend['baseline']:.4f}")
    print(("PASS" if run.passed else "FAIL") + (f" - stopped: {run.stopped}" if run.stopped else "")
          + f"; report {report_path}")
    return 0 if run.passed else 1


if __name__ == "__main__":
    sys.exit(main())
