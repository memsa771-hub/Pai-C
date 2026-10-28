"""The rehearsal driver (Slice 9a spec §2.4, §2.5, S9-D12; plan rulings 3 and 4): fictional students play the whole
Germany master's route through PAI OS's API, on rehearsal time, with offline AI, against a real worker process.

    Rehearsal(["S1", "S3"], out_dir).run() -> Report         (python -m tests.os.rehearsal.run for the command)

One rehearsal:
1. clean `os_test` (every os_* table, the DBOS schema), load the playbook's programme registry and the seeded facts,
   write a fresh offline answers folder (controller ruling 1), set the clock to 1 Dec 2026 (advance from real time in
   steps of at most 60 days), start one worker subprocess (OS_REHEARSAL=on, OS_MODEL_MODE=offline);
2. each student agrees to the (placeholder) pilot terms, starts a self-serve plan and uploads their documents;
3. loop: each student answers what their inbox, documents, statements, packs and visa file ask, as `students.yaml`
   says; the driver waits for the worker to finish (no queued workflow, no unsent kernel request, no document being
   read); then it advances 1-3 days and ticks. It stops when every plan has `visa_apply` waiting, is stuck, or the date
   is past 30 Sep 2027;
4. the scripted events are checked against spec §2.4's table; a miss is a failure;
5. the report (counts and states only) and the failure log (outside the repo) are written.

The API runs in this process (a FastAPI app with a test-student header, like tests/os/test_api.py); the worker is a
subprocess, so `kill=True` can SIGKILL it at random points and start it again with the same executor ID (Linux only;
the tests/os/test_crash.py pattern). The driver never changes plan state itself: it acts only through the API, and
reads the database only to check results and to know when the worker is idle.

End points (spec 9a gate 1): **ready to submit** = for every live programme an apply step (`uni_assist_apply` or
`direct_apply`) waits for the student and that programme's pack is approved; the student then says "I submitted it".
**Visa file ready** = `visa_apply` waits for the student and the visa file is approved.

Test code: country words and fictional names are allowed here (invariant 12 covers app/os only)."""

import io
import json
import logging
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import Engine, create_engine, func, select, text

from app.os import clock, models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents.types import load_document_types
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed
from app.os.replan import events as replan_events
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema, run_alembic, truncate_os_tables
from tests.os.rehearsal import make_answers
from tests.os.rehearsal.failures import Failure, FailureLog
from tests.os.rehearsal.report import Report, StudentResult

log = logging.getLogger("tests.os.rehearsal")

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
STUDENTS_FILE = HERE / "students.yaml"
ANSWERS = make_answers.ANSWERS
SAMPLES = make_answers.SAMPLES
START = date(2026, 12, 1)
END = date(2027, 9, 30)
STUCK_DAYS = 30
P = "/v1/os"
ROUTE = "germany_master"
INTAKE = {"term": "winter", "year": 2027}
TENANT = "pai"  # the default tenant (OS_TENANT_ID unset), on the API and the worker
TOKEN = "rehearsal-admin-token"  # a fictional token for this in-process API only
ADMIN = {"X-OS-Admin-Token": TOKEN}
WORKER_ID = "rehearsal-w0"
ROUNDS_PER_DAY = 6  # act -> wait for the worker, again, while a student still acted
SETTLE_S = 180.0
TICK_S = 180.0
BUNDLE_TYPES = ("passport", "degree_certificate", "transcript", "ssc_certificate", "hssc_certificate", "ielts_trf")
APPLY_STEPS = ("uni_assist_apply", "direct_apply")
NOTICE = "plan_updated"
CANCELLED_MARK, DONE_MARK = "#c", "#d"
OPEN_STATES = ("pending", "ready", "running", "waiting_student", "waiting_review", "blocked", "failed")
# The step a document belongs to (for the failure log's `step`); documents with no step are None.
DOC_STEP = {"degree_certificate": "hec_attestation", "transcript": "hec_attestation",
            "ssc_certificate": "school_certificates", "hssc_certificate": "school_certificates",
            "min_passing_grade_letter": "min_passing_grade_letter", "ielts_trf": "english_test",
            "blocked_account_confirmation": "blocked_account", "insurance_certificate": "travel_insurance",
            "admission_letter": "admission_result"}
# What the visa file needs that is not ready on day one: these documents come when their step does.
STEP_DOCS = {"blocked_account": "blocked_account_confirmation", "travel_insurance": "insurance_certificate"}
# visa_target_date has no official source (seed comment; Spike 5 C5): the rehearsal's admin supplies one when a plan
# waits for it, as an admin would through the open-facts screen, and logs that it had to (a workaround).
VISA_TARGET = {"date": "2027-09-01", "tz": "Europe/Berlin"}


# --------------------------------------------------------------------------------------------------- students file


@dataclass(frozen=True)
class Student:
    sid: str
    programmes: tuple[str, ...]
    bundle: int
    event: str
    interview: dict
    admission: dict
    visa_programme: str
    details: dict
    resolve: dict
    withhold: str | None = None
    sop_addition: str | None = None

    def files(self) -> dict[str, str]:
        """The student's sample documents: document type -> file name in the Spike 2 sample set."""
        return {t: f"b{self.bundle}_{t}.png" for t in BUNDLE_TYPES}


def load_students(path: Path = STUDENTS_FILE) -> dict[str, Student]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["students"]
    out = {}
    for sid, s in raw.items():
        a = s["answers"]
        out[sid] = Student(sid=sid, programmes=tuple(s["programmes"]), bundle=int(s["bundle"]), event=s["event"],
                           interview=dict(a["interview"]), admission=dict(a["admission"]),
                           visa_programme=a["visa_programme"], details={k: str(v) for k, v in a["details"].items()},
                           resolve=dict(a.get("resolve") or {}), withhold=a.get("withhold"),
                           sop_addition=a.get("sop_addition"))
    return out


def student_ref(sid: str) -> str:
    """The student reference the API sees for S1..S12 (no names)."""
    return f"rehearsal-{sid.lower()}"


# --------------------------------------------------------------------------------------------------- pure rules


def should_stop(today: date, states: dict[str, str], end: date = END) -> bool:
    """Stop when the date is past the end (30 Sep 2027), or no student is still running (spec §2.4 step 3)."""
    return today > end or all(s != "running" for s in states.values())


class StuckWatch:
    """S9-D12: a plan is stuck when STUCK_DAYS rehearsal days pass with no change while nothing waits on the student.
    `see` is called once per loop with the plan's fingerprint (any change of state or revision changes it); it returns
    a `blocks` failure the first time a student is stuck, else None."""

    def __init__(self, days: int = STUCK_DAYS) -> None:
        self.days = days
        self._since: dict[str, tuple[date, object]] = {}
        self._reported: set[str] = set()

    def see(self, student: str, today: date, fingerprint: object, waiting: bool) -> Failure | None:
        since = self._since.get(student)
        if waiting or since is None or since[1] != fingerprint:
            self._since[student] = (today, fingerprint)
            return None
        if (today - since[0]).days < self.days or student in self._reported:
            return None
        self._reported.add(student)
        return Failure(f"stuck:{student}", student, None, f"a change within {self.days} rehearsal days",
                       f"stuck: no change for {(today - since[0]).days} days with nothing waiting on the student",
                       "blocks")


# --------------------------------------------------------------------------------------------------- documents


def _person(bundle: int) -> str:
    """The bundle person's full name, as their school certificates print it (fictional)."""
    key = yaml.safe_load((SAMPLES / make_answers.KEY_NAME).read_text(encoding="utf-8"))["documents"]
    return key[f"b{bundle}_hssc_certificate.png"]["fields"]["student_name"]


def extra_documents(student: Student, programmes: dict[str, tuple[str, str]]) -> dict[str, tuple[str, dict]]:
    """The four documents the sample bundles lack, made from the bundle person's own name: file name -> (type,
    values). `programmes` gives (university, name) per programme ref, for the admission letter."""
    name = _person(student.bundle)
    university, programme = programmes[student.visa_programme]
    n = student.sid.lower()
    return {
        f"{n}_min_passing_grade_letter.png": ("min_passing_grade_letter", {
            "institution": "University of Exampleton", "scale_best": 4.0, "min_pass": 2.0, "issue_date": "2024-03-01"}),
        f"{n}_admission_letter.png": ("admission_letter", {
            "student_name": name, "institution": university, "programme": programme, "start_date": "2027-10-01",
            "issue_date": "2027-02-01"}),
        f"{n}_blocked_account_confirmation.png": ("blocked_account_confirmation", {
            "holder_name": name, "provider": "Sample Blocked Accounts", "amount": 11904, "monthly_payout": 992,
            "issue_date": "2027-01-10"}),
        f"{n}_insurance_certificate.png": ("insurance_certificate", {
            "holder_name": name, "insurer": "Sample Health Insurance", "cover_start": "2027-09-15",
            "cover_end": "2028-09-14"}),
    }


def render_page(title: str, owner: str, values: dict) -> bytes:
    """A plain A4 page marked as a sample, one line per value. Deterministic for the installed Pillow."""
    img = Image.new("RGB", (1000, 1414), (252, 252, 248))
    d = ImageDraw.Draw(img)
    d.rectangle((12, 12, 987, 1401), outline=(60, 60, 90), width=3)
    d.text((40, 30), "SAMPLE - TEST DOCUMENT", font=ImageFont.load_default(size=30), fill=(200, 30, 30))
    d.text((40, 80), title.upper(), font=ImageFont.load_default(size=36), fill=(20, 20, 60))
    d.text((40, 130), f"Rehearsal {owner}", font=ImageFont.load_default(size=22), fill=(90, 90, 90))
    y = 200
    for key, value in values.items():
        d.text((40, y), f"{key.replace('_', ' ').capitalize()}: {value}", font=ImageFont.load_default(size=26),
               fill=(10, 10, 10))
        y += 48
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _reader():
    return load_document_types(), load_agent_spec(AGENT_DIR / "documents.v1.yaml").mode


def answer_key(name: str, data: bytes, doc_type: str) -> str:
    """The offline documents answer key for this file: the SHA-256 of the first image the documents model sees."""
    types, mode = _reader()
    return make_answers.first_image_sha(name, data, doc_type, types, mode)


def build_answers(dest: Path, extras: dict[str, tuple[str, dict, bytes]]) -> Path:
    """A fresh answers folder (controller ruling 1): the fixed answer files copied, `documents.yaml` written again by
    make_answers (so its keys match the installed Pillow), plus one answer per extra document."""
    dest.mkdir(parents=True, exist_ok=True)
    for f in ANSWERS.glob("*.yaml"):
        if f.name != "documents.yaml":
            shutil.copy(f, dest / f.name)
    path = make_answers.write(dest)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    types, mode = _reader()
    for name, (doc_type, values, raw) in sorted(extras.items()):
        sha = make_answers.first_image_sha(name, raw, doc_type, types, mode)
        data[sha] = {"file": name, "values": {**{f.name: values.get(f.name) for f in types[doc_type].fields},
                                              "detected_type": doc_type}}
    path.write_text(make_answers.HEADER + yaml.safe_dump(data, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return dest


def missing_answer(sid: str, doc_type: str, name: str, data: bytes, answers_dir: Path) -> Failure | None:
    """Review Focus 5: a document that ended failed. If the offline answers have no entry for the image the model saw,
    a failure naming the missing key and the file; else None (the caller logs a plain document failure)."""
    sha = answer_key(name, data, doc_type)
    known = yaml.safe_load((answers_dir / "documents.yaml").read_text(encoding="utf-8")) or {}
    if sha in known:
        return None
    return Failure(f"missing_answer:{sid}:{doc_type}", sid, DOC_STEP.get(doc_type), "the document is read",
                   f"missing offline answer documents:{sha} ({name})", "blocks")


# --------------------------------------------------------------------------------------------------- duplicates

# What would be done twice if a step ran again after a kill and its work were not idempotent. Each is something the
# schema does NOT already forbid: a document has one agent-run row by a unique key (`document:<id>`), and the outbox one
# row per idempotency key, so those cannot be counted. Name -> what a clean run shows.
DUPLICATE_CHECKS = {
    "proposal_per_event": "one replan proposal per event",
    "revision_per_proposal": "at most one plan revision per replan proposal",
    "support_case_per_proposal": "at most one support case per replan proposal",
    "attempt_without_failure": "a work task runs as a new attempt only after it failed",
    "manifest_built_twice": "a pack or visa file version differs from the version before it",
    "draft_per_request": "one Writer version per draft request",
}


def duplicates(engine: Engine, drafts: dict[str, dict[tuple[str, str | None], int]]) -> dict[str, list[str]]:
    """Duplicated work in the database: check name (DUPLICATE_CHECKS) -> what was found twice. `drafts` gives, per
    student reference, how many draft requests the driver sent per (kind, programme), for `draft_per_request`."""
    PR, R, C, T, TA, E = (models.proposals, models.plan_revisions, models.support_cases, models.tasks,
                          models.task_attempts, models.events)
    A, V = models.artifacts, models.artifact_versions
    found: dict[str, list[str]] = {}
    with engine.connect() as conn:
        per_event: dict[int, int] = {}
        for ids in conn.execute(select(PR.c.event_ids)).scalars():
            for i in ids or []:
                per_event[i] = per_event.get(i, 0) + 1
        found["proposal_per_event"] = [f"event {i}" for i, n in sorted(per_event.items()) if n > 1]
        found["revision_per_proposal"] = [f"{cause} on plan {plan}" for plan, cause, n in conn.execute(
            select(R.c.plan_id, R.c.cause, func.count()).where(R.c.cause.like("replan:%"))
            .group_by(R.c.plan_id, R.c.cause).having(func.count() > 1)).all()]
        found["support_case_per_proposal"] = [f"proposal {p}" for p, n in conn.execute(
            select(C.c.proposal_id, func.count()).where(C.c.proposal_id.is_not(None))
            .group_by(C.c.proposal_id).having(func.count() > 1)).all()]
        failed = set(conn.execute(select(E.c.task_id).where(E.c.type == "task_failed")).scalars().all())
        found["attempt_without_failure"] = [f"task {task}" for task, n in conn.execute(
            select(TA.c.task_id, func.count()).join(T, T.c.id == TA.c.task_id).where(T.c.kind == "work")
            .group_by(TA.c.task_id).having(func.count() > 1)).all() if task not in failed]
        rows = conn.execute(select(A.c.id, A.c.kind, V.c.number, V.c.text).join(V, V.c.artifact_id == A.c.id)
                            .where(A.c.kind.in_(("pack", "visa"))).order_by(A.c.id, V.c.number)).all()
        last: dict[int, str | None] = {}
        twice = []
        for art, kind, number, text_ in rows:
            try:
                inputs = json.loads(text_).get("inputs_sha256")  # a manifest version's text is its JSON
            except (ValueError, AttributeError):
                inputs = None
            if inputs is not None and last.get(art) == inputs:
                twice.append(f"{kind} {art} version {number}")
            last[art] = inputs
        found["manifest_built_twice"] = twice
        writer = conn.execute(select(A.c.student_ref, A.c.kind, A.c.programme_ref, func.count())
                              .join(V, V.c.artifact_id == A.c.id).where(V.c.author == "writer")
                              .group_by(A.c.student_ref, A.c.kind, A.c.programme_ref)).all()
        found["draft_per_request"] = [f"{kind} of {student}" for student, kind, ref, n in writer
                                      if student in drafts and n > drafts[student].get((kind, ref or None), 0)]
    return {k: v for k, v in found.items() if v}


# --------------------------------------------------------------------------------------------------- the worker


class Worker:
    """One worker subprocess with a stable executor ID; SIGKILL and start again keeps the ID, so DBOS recovers it."""

    def __init__(self, env: dict, log_dir: Path) -> None:
        self.env, self.log_dir = env, log_dir
        self.proc: subprocess.Popen | None = None
        self.generation = 0
        self.kills = 0

    def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        out = open(self.log_dir / f"worker-g{self.generation}.log", "wb")
        self.generation += 1
        self.proc = subprocess.Popen([sys.executable, "-m", "app.os.runner.worker"], cwd=BACKEND, env=self.env,
                                     stdout=out, stderr=subprocess.STDOUT)
        out.close()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()
        self.kills += 1

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


# --------------------------------------------------------------------------------------------------- one student


@dataclass
class Run:
    """What the driver knows about one student while the rehearsal runs."""

    s: Student
    ref: str
    plan_id: int | None = None
    state: str = "running"
    reached: list[str] = field(default_factory=list)
    events: dict[str, str] = field(default_factory=dict)  # event -> ok | missed
    days: int = 0
    uploads: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # doc type -> (file name, bytes)
    docs_logged: set[int] = field(default_factory=set)
    findings_seen: set[str] = field(default_factory=set)  # fields of mismatch findings shown to the student
    resolved: set[int] = field(default_factory=set)
    details_saved: set[str] = field(default_factory=set)  # "pack" | "visa"
    ticked: set[str] = field(default_factory=set)
    accepted: list[int] = field(default_factory=list)
    sop_changed: bool = False
    sop_id: int | None = None  # the base SOP's id, as the statements page showed it
    drafts: dict[tuple[str, str | None], int] = field(default_factory=dict)  # draft requests per (kind, programme)
    released: bool = False  # S7: the plan asked for the late step; S5: a support case was opened
    incomplete_since: dict[str, date] = field(default_factory=dict)


def _template(instance_key: str) -> str:
    return instance_key.split("@")[0].split("#")[0]


def _live(t: dict) -> bool:
    return CANCELLED_MARK not in t["instance_key"] and DONE_MARK not in t["instance_key"]


# --------------------------------------------------------------------------------------------------- the rehearsal


class Rehearsal:
    def __init__(self, students: list[str], out_dir: Path, *, kill: bool = False, end: date = END,
                 seed: int = 9, answers_edit: Callable[[Path], None] | None = None,
                 check_finish: bool | None = None, database_url: str | None = None) -> None:
        """`end`, `answers_edit` and `check_finish` are for tests: a shorter run, a changed answers folder (Review
        Focus 5), and whether a student who has not finished by the end is a failure (default: only with the real
        end date)."""
        every = load_students()
        unknown = [s for s in students if s not in every]
        if unknown:
            raise ValueError(f"unknown students: {', '.join(unknown)}")
        self.students = [every[s] for s in students]
        self.out_dir = Path(out_dir).expanduser()
        self.kill, self.end, self.rng, self.answers_edit = kill, end, random.Random(seed), answers_edit
        self.check_finish = (end == END) if check_finish is None else check_finish
        self.url = database_url or os.environ.get("OS_TEST_DATABASE_URL") or ""
        if not self.url:
            raise ValueError("OS_TEST_DATABASE_URL is not set (the rehearsal cleans that database)")
        if (self.out_dir / "failures.yaml").exists():  # a log may carry hand-written fixed_by / owner_accepted
            raise ValueError(f"{self.out_dir} already holds a rehearsal; choose a new folder")
        self.failures = FailureLog(self.out_dir / "failures.yaml")
        self.watch = StuckWatch()
        self.start: date = START
        self.admin_actions: list[str] = []

    # ------------------------------------------------------------------ helpers

    def fail(self, id_: str, student: str, step: str | None, expected: str, got: str, severity: str = "blocks"):
        if self.failures.add(Failure(id_, student, step, expected, str(got)[:400], severity)):
            log.warning("rehearsal failure %s: %s", id_, got)

    def call(self, run: Run | None, method: str, path: str, *, step: str | None = None,
             ok: Iterable[int] = (200, 201, 202, 204), **kw):
        """One API call as the student (or as the admin when `run` is None). An unexpected status is a failure (one
        per student, call shape and status) and gives None."""
        headers = dict(ADMIN) if run is None else {"X-Test-Student": run.ref}
        r = self.client.request(method, P + path, headers=headers, **kw)
        if r.status_code in tuple(ok):
            return r
        shape = re.sub(r"/\d+", "/{id}", path.split("?")[0])
        who = run.s.sid if run else "admin"
        detail = r.text[:300]
        self.fail(f"http:{who}:{method} {shape}:{r.status_code}", who, step, f"{method} {shape} succeeds",
                  f"{r.status_code} {detail}")
        return None

    def get(self, run, path, **kw):
        r = self.call(run, "GET", path, **kw)
        return None if r is None else r.json()

    # ------------------------------------------------------------------ set-up

    def _clean(self) -> None:
        run_alembic(["upgrade", "os@head"], self.url)
        truncate_os_tables(self.engine)
        reset_dbos_schema(self.url)
        kb, store = SqlKnowledge(self.engine, TENANT), ProgrammeStore(self.engine, TENANT)
        load_programme_seed(PROGRAMME_SEED, store)
        load_seed(SEED_DIR / "germany_ws2027.yaml", kb)

    def _answers(self) -> None:
        store = ProgrammeStore(self.engine, TENANT)
        programmes = {}
        for s in self.students:
            for ref in s.programmes:
                p = store.get(ref)
                programmes[ref] = (p.university, p.name)
        self.extras: dict[str, dict[str, tuple[str, bytes]]] = {}
        flat: dict[str, tuple[str, dict, bytes]] = {}
        for s in self.students:
            mine = {}
            for name, (doc_type, values) in extra_documents(s, programmes).items():
                raw = render_page(doc_type.replace("_", " "), s.sid, values)
                mine[doc_type] = (name, raw)
                flat[name] = (doc_type, values, raw)
            self.extras[s.sid] = mine
        self.answers_dir = build_answers(Path(self.tmp) / "answers", flat)
        if self.answers_edit is not None:
            self.answers_edit(self.answers_dir)

    def _api(self) -> None:
        env = {"OS_DATABASE_URL": self.url, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_ADMIN_TOKEN": TOKEN,
               "OS_ENABLED": "true", "OS_REHEARSAL": "on", "OS_MODEL_MODE": "offline",
               "OS_OFFLINE_ANSWERS_DIR": str(self.answers_dir)}
        self.settings = load_settings(env)
        self.svc = make_services(self.settings, engine=self.engine)  # installs the rehearsal clock
        app = FastAPI()
        app.include_router(build_router(lambda: self.svc), prefix=P)

        def student(x_test_student: str | None = Header(None)) -> str:
            if not x_test_student:
                raise HTTPException(401)
            return x_test_student

        app.dependency_overrides[current_student_ref] = student
        app.dependency_overrides[current_student_ref_for_write] = student
        self.client = TestClient(app, raise_server_exceptions=False)  # a 500 is a logged failure, not a crash

    def _set_clock(self) -> None:
        """The rehearsal starts on START whatever the real date: the admin `start` call sets the clean clock once
        (a day in the past too). If it is refused, the run goes on from the clock's today and logs start_late."""
        if self.call(None, "POST", "/admin/rehearsal/start", json={"date": START.isoformat()}) is None:
            today = clock.today()
            log.warning("the rehearsal clock could not be set to %s: starting from %s", START, today)
            self.fail(f"start_late:{today.isoformat()}", "all", None, f"the rehearsal starts on {START.isoformat()}",
                      f"the start call was refused; the clock's today is {today.isoformat()}", "workaround")
        self.start = clock.today()

    def _worker(self) -> None:
        env = {**os.environ, "OS_DATABASE_URL": self.url, "OS_TEST_DATABASE_URL": self.url,
               "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_WORKER_ID": WORKER_ID, "OS_REHEARSAL": "on",
               "OS_MODEL_MODE": "offline", "OS_OFFLINE_ANSWERS_DIR": str(self.answers_dir),
               "OS_EMAIL_SENDER": "log", "OS_PARENT_PID": str(os.getpid())}
        for k in ("OS_OPENAI_API_KEY", "OS_TEST_RESEARCH_MODEL", "OS_TEST_DOCUMENT_MODEL", "OS_TEST_STATEMENT_MODEL",
                  "OS_TEST_REPLAN_MODEL", "OS_EXTRA_MODULES"):
            env.pop(k, None)
        self.worker = Worker(env, self.out_dir / "logs")
        self.worker.start()
        self._wait_queue()

    def _wait_queue(self) -> None:
        from app.os.runner import QUEUE_NAME

        end = time.monotonic() + 90
        while time.monotonic() < end:
            try:
                if self.svc.dbos_client().retrieve_queue(QUEUE_NAME) is not None:
                    return
            except Exception:  # noqa: BLE001  (the DBOS tables are not created yet)
                pass
            if not self.worker.alive():
                raise RuntimeError(f"the worker stopped during startup (logs: {self.out_dir / 'logs'})")
            time.sleep(0.3)
        raise TimeoutError("the worker did not register the queue")

    # ------------------------------------------------------------------ waiting for the worker

    def _busy(self) -> str | None:
        with self.engine.connect() as conn:
            flows = conn.execute(text(f"SELECT count(*) FROM {TEST_DBOS_SCHEMA}.workflow_status "
                                      "WHERE status IN ('PENDING', 'ENQUEUED')")).scalar()
            unsent = conn.execute(select(func.count()).select_from(models.enqueue_requests).where(
                models.enqueue_requests.c.sent.is_(False))).scalar()
            reading = conn.execute(select(func.count()).select_from(models.documents).where(
                models.documents.c.status.in_(("uploaded", "reading")))).scalar()
        if flows or unsent or reading:
            return f"{flows} workflows, {unsent} unsent requests, {reading} documents being read"
        return None

    def settle(self) -> None:
        """Waits until the worker has nothing left to do (twice in a row, 0.15 s apart). In a kill run it first
        SIGKILLs the worker now and then while it is busy, and starts it again with the same executor ID."""
        end, quiet = time.monotonic() + SETTLE_S, 0
        if self.kill and self.rng.random() < 0.2 and self._busy() is not None:  # a kill while work is in flight
            time.sleep(self.rng.uniform(0.0, 0.5))
            self.worker.kill()
            self.worker.start()
        while True:
            if not self.worker.alive():
                self.fail("worker_exited", "all", None, "the worker keeps running", "the worker process exited")
                self.worker.start()
            busy = self._busy()
            quiet = quiet + 1 if busy is None else 0
            if quiet >= 2:
                return
            if time.monotonic() > end:
                self.fail("worker_busy", "all", None, f"the worker finishes within {SETTLE_S:.0f} s", busy)
                return
            time.sleep(0.15)

    def advance(self, days: int) -> None:
        self.call(None, "POST", "/admin/rehearsal/advance", json={"days": days})

    def tick(self) -> None:
        r = self.call(None, "POST", "/admin/rehearsal/tick")
        if r is None:
            return
        tick_id = r.json()["tick_id"]
        if self.kill and self.rng.random() < 0.35:  # a kill while the tick (and what it enqueues) is in flight
            time.sleep(self.rng.uniform(0.0, 0.6))
            self.worker.kill()
            self.worker.start()
        end = time.monotonic() + TICK_S
        while time.monotonic() < end:
            got = self.get(None, f"/admin/rehearsal/tick/{tick_id}")
            if got is None:
                return
            if got["status"] == "done":
                return
            if got["status"] == "error":
                for job in got["failed"] or ["workflow"]:
                    self.fail(f"tick_failed:{job}", "all", None, f"the tick's job {job} runs", "it failed (worker log)")
                return
            if not self.worker.alive():
                self.worker.start()
            time.sleep(0.1)
        self.fail("tick_timeout", "all", None, f"a tick ends within {TICK_S:.0f} s", "still running")

    # ------------------------------------------------------------------ the run

    def run(self) -> Report:
        self.tmp = tempfile.mkdtemp(prefix="s9-rehearsal-")
        self.engine: Engine = create_engine(self.url, pool_pre_ping=True)
        self.worker = None
        self.svc = None
        try:
            self._clean()
            self._answers()
            self._api()
            self._set_clock()
            self._worker()
            runs = [Run(s, student_ref(s.sid)) for s in self.students]
            for run in runs:
                self._safe(run, self._begin)
            self.settle()
            self._loop(runs)
            self._final(runs)
            report = self._report(runs)
        finally:
            if self.worker is not None:
                self.worker.stop()
            if self.svc is not None:
                try:
                    self.svc.dbos_client().destroy()
                except Exception:  # noqa: BLE001
                    pass
            clock.configure(None)  # this process goes back to real time
            self.engine.dispose()
            shutil.rmtree(self.tmp, ignore_errors=True)
        report.write(self.out_dir)
        return report

    def _safe(self, run: Run, fn) -> bool:
        """One student's step; an exception is a failure for that student and the others carry on."""
        try:
            return bool(fn(run))
        except Exception as e:  # noqa: BLE001
            log.exception("driver error for %s", run.s.sid)
            self.fail(f"driver_error:{run.s.sid}:{type(e).__name__}", run.s.sid, None, "the driver's step runs",
                      f"{type(e).__name__}: {e}")
            return False

    def _loop(self, runs: list[Run]) -> None:
        while True:
            today = clock.today()
            for _ in range(ROUNDS_PER_DAY):
                acted = False
                for run in runs:
                    if run.state == "running":
                        acted |= self._safe(run, self._act)
                if not acted:
                    break  # nothing new for the worker: the last wait still holds
                self.settle()
            for run in runs:
                if run.state == "running":
                    self._safe(run, lambda r: self._observe(r, today))
                    run.days = (today - self.start).days
            if should_stop(today, {r.s.sid: r.state for r in runs}, self.end):
                return
            self.advance(self.rng.randint(1, 3))
            self.tick()
            self.settle()

    # ------------------------------------------------------------------ step 2: begin

    def _begin(self, run: Run) -> bool:
        s = run.s
        terms = self.get(run, "/consent")
        self.call(run, "POST", "/consent", json={"version": terms["version"]}, step="consent")
        r = self.call(run, "POST", "/plans/self", step="choose_programmes", json={
            "route": ROUTE, "intake": INTAKE,
            "choices": [{"programme_ref": ref, "rank": n} for n, ref in enumerate(s.programmes, 1)]})
        if r is None:
            run.state = "not_finished"
            return False
        run.plan_id = r.json()["plan_id"]
        for doc_type, name in s.files().items():
            self._upload(run, doc_type, name, (SAMPLES / name).read_bytes())
        if s.withhold != "min_passing_grade_letter":
            self._upload_extra(run, "min_passing_grade_letter")
        return True

    def _upload(self, run: Run, doc_type: str, name: str, data: bytes) -> None:
        if doc_type in run.uploads:
            return
        run.uploads[doc_type] = (name, data)
        self.call(run, "POST", "/documents", step=DOC_STEP.get(doc_type), data={"doc_type": doc_type},
                  files={"file": (name, data, "image/png")})

    def _upload_extra(self, run: Run, doc_type: str) -> None:
        name, data = self.extras[run.s.sid][doc_type]
        self._upload(run, doc_type, name, data)

    # ------------------------------------------------------------------ step 3: one round for one student

    def _plan(self, run: Run) -> dict:
        return self.get(None, f"/plans/{run.plan_id}") or {"tasks": [], "revision": 0, "status": "?"}

    def _act(self, run: Run) -> bool:
        acted = self._documents(run)
        inbox = self.get(run, "/inbox")
        if inbox is None:
            return acted
        for note in inbox["notes"]:
            acted |= self.call(run, "POST", f"/inbox/notes/{note['id']}/read") is not None
        acted |= self._proposals(run, inbox["proposals"])
        if run.s.event == "late" and not run.released:
            run.released = self._asked_for(run)
            if not run.released:  # S7 answers nothing but plan notices until the plan asks for the late step
                return self._notices(run, inbox["items"]) or acted
        if run.s.withhold and not run.released:
            run.released = self._missing_case(run) is not None
            if run.released:
                self._upload_extra(run, run.s.withhold)
                acted = True
        plan = self._plan(run)
        tasks = {t["instance_key"]: t for t in plan["tasks"] if _live(t)}
        waiting = {t["instance_key"]: t for t in inbox["items"]}
        by_template: dict[str, list[dict]] = {}
        for t in waiting.values():
            by_template.setdefault(_template(t["instance_key"]), []).append(t)
        self._inbox_matches_plan(run, tasks, waiting)
        if "application_documents" in by_template:
            acted |= self._statements(run)
        if "review_pack" in by_template:
            acted |= self._packs(run, [t["programme_ref"] for t in by_template["review_pack"]])
        acted |= self._apply(run, tasks, by_template)
        for t in by_template.get("admission_result", []):
            ref = t["programme_ref"]
            choice = run.s.admission.get(ref, "admitted")
            if self.call(run, "POST", f"/inbox/{t['id']}/complete", step="admission_result",
                         json={"payload": {"choice": choice}}) is not None:
                acted = True
                if choice == "admitted" and ref == run.s.visa_programme:
                    self._upload_extra(run, "admission_letter")
        for template, doc_type in STEP_DOCS.items():
            for t in by_template.get(template, []):
                self._upload_extra(run, doc_type)
                acted |= self._complete(run, t)
        if "review_visa_file" in by_template:
            acted |= self._visa(run)
        acted |= self._visa_ready(run, tasks)
        done = {"application_documents", "review_pack", "admission_result", "review_visa_file", "visa_apply",
                *APPLY_STEPS, *STEP_DOCS}
        for template, items in by_template.items():
            if template in done:
                continue
            if template == run.s.withhold and not run.released:
                continue  # S5 never provides it unless a person follows up
            for t in items:
                acted |= self._complete(run, t)
        return acted

    def _inbox_matches_plan(self, run: Run, tasks: dict, waiting: dict) -> None:
        """Every student step the plan (admin view) says waits for the student must be in their inbox. The inbox is
        read once more first, since a step can start waiting between the two reads."""
        missing = [k for k, t in tasks.items() if t["kind"] == "student" and t["state"] == "waiting_student"
                   and k not in waiting]
        if not missing:
            return
        again = {t["instance_key"] for t in (self.get(run, "/inbox") or {"items": []})["items"]}
        for key in missing:
            if key not in again and tasks[key]["state"] == "waiting_student":
                self.fail(f"inbox_missing:{run.s.sid}:{_template(key)}", run.s.sid, _template(key),
                          "a step waiting for the student is in their inbox", f"{key} waits but is not in the inbox")

    def _complete(self, run: Run, t: dict, payload: dict | None = None) -> bool:
        return self.call(run, "POST", f"/inbox/{t['id']}/complete", step=_template(t["instance_key"]),
                         json={"payload": payload or {}}) is not None

    def _notices(self, run: Run, items: list[dict]) -> bool:
        return any([self._complete(run, t) for t in items if _template(t["instance_key"]) == NOTICE])

    # documents: confirm what was read as read; resolve a mismatch with the student's right value
    def _documents(self, run: Run) -> bool:
        out = self.get(run, "/documents")
        if out is None:
            return False
        acted = False
        for doc in out["documents"]:
            if doc["status"] == "read":
                fields = {f["field"]: f["value_read"] for f in doc["fields"]}
                acted |= self.call(run, "POST", f"/documents/{doc['id']}/confirm", step=DOC_STEP.get(doc["doc_type"]),
                                   json={"fields": fields}) is not None
            elif doc["status"] in ("failed", "needs_student") and doc["id"] not in run.docs_logged:
                run.docs_logged.add(doc["id"])
                name, data = run.uploads.get(doc["doc_type"], (doc["filename"], b""))
                missing = missing_answer(run.s.sid, doc["doc_type"], name, data, self.answers_dir) if data else None
                if missing is not None:
                    self.failures.add(missing)
                else:
                    self.fail(f"document_{doc['status']}:{run.s.sid}:{doc['doc_type']}", run.s.sid,
                              DOC_STEP.get(doc["doc_type"]), "the document is read",
                              f"status {doc['status']}: {doc['error']}")
        if acted:  # a confirm checks the documents again, and may replace the open findings
            out = self.get(run, "/documents") or {"findings": []}
        for finding in out["findings"]:
            if finding["id"] in run.resolved:
                continue
            run.findings_seen.add(f"{finding['kind']}:{finding['field']}")
            right = run.s.resolve.get(finding["field"])
            if right is None:
                self.fail(f"unexpected_finding:{run.s.sid}:{finding['field']}", run.s.sid, None,
                          "no finding on a consistent bundle", f"a {finding['kind']} finding on {finding['field']}")
                run.resolved.add(finding["id"])
                continue
            values = {str(i["value"]) for i in finding["items"]}
            if str(right) not in values:
                self.fail(f"finding_without_right_value:{run.s.sid}:{finding['field']}", run.s.sid, None,
                          "the right value is one of the choices", f"choices: {len(values)}")
                run.resolved.add(finding["id"])
                continue
            resolved = self.call(run, "POST", f"/documents/findings/{finding['id']}/resolve", json={"value": right})
            if resolved is not None:
                run.resolved.add(finding["id"])
                acted = True
        return acted

    # suggestions: accept, unless this student ignores big suggestions
    def _proposals(self, run: Run, proposals: list[dict]) -> bool:
        acted = False
        for p in proposals:
            if run.s.event == "ignore_big" and p["big"]:
                continue  # S11 leaves it unanswered: it must expire
            if p["id"] in run.accepted:
                continue
            run.accepted.append(p["id"])
            acted |= self.call(run, "POST", f"/proposals/{p['id']}/accept", step="replan") is not None
        return acted

    def _changes(self, run: Run) -> dict:
        return self.get(run, "/changes") or {"changes": [], "pending": []}

    def _asked_for(self, run: Run) -> bool:
        """S7: the plan asked the student for a step (an applied change with request_from_student)."""
        return any(o["op"] == "request_from_student" for c in self._changes(run)["changes"] for o in c["ops"])

    def _support_case(self, run: Run) -> dict | None:
        cases = (self.get(None, "/admin/support") or {"cases": []})["cases"]
        return next((c for c in cases if c["plan_id"] == run.plan_id), None)

    def _missing_case(self, run: Run) -> dict | None:
        """S5: the support case opened for the withheld step: one that names an `escalate` event of that step (its
        date passed with the document still missing), not any case on the plan."""
        cases = [c for c in (self.get(None, "/admin/support") or {"cases": []})["cases"] if c["plan_id"] == run.plan_id]
        if not cases:
            return None
        E = models.events
        with self.engine.connect() as conn:
            escalations = set(conn.execute(select(E.c.id).where(
                E.c.plan_id == run.plan_id, E.c.type == "escalate",
                E.c.payload["instance_key"].astext == run.s.withhold)).scalars().all())
        return next((c for c in cases if set(c["event_ids"]) & escalations), None)

    # statements: answer the interview, draft and approve the SOP and the CV (and a programme's own SOP if asked)
    def _statements(self, run: Run) -> bool:
        acted = False
        interview = self.get(run, "/statements/interview")
        if interview is None:
            return False
        for qid in interview["missing"]:
            answer = run.s.interview.get(qid, "I have nothing more to add for this question.")
            acted |= self.call(run, "PUT", f"/statements/answers/{qid}", json={"answer": answer}) is not None
        listed = self.get(run, "/statements")
        if listed is None:
            return acted
        wanted = [("sop", None), ("cv", None)] + [("sop", p["programme_ref"]) for p in listed["programmes"]
                                                  if p.get("needed")]
        have = {(s["kind"], s["programme_ref"]): s for s in listed["statements"]}
        if ("sop", None) in have:
            run.sop_id = have[("sop", None)]["id"]
        for kind, ref in wanted:
            st = have.get((kind, ref))
            if st is None or st["status"] == "empty" or st["version"] is None:
                if st is None or st["status"] != "drafting":
                    sent = self.call(run, "POST", f"/statements/{kind}/draft", step="application_documents",
                                     json={"programme_ref": ref}) is not None
                    if sent:
                        run.drafts[(kind, ref)] = run.drafts.get((kind, ref), 0) + 1
                    acted |= sent
                continue
            if st["status"] == "drafting":
                continue
            if st["approval"] is None or st["approval"]["version"] != st["version"]["number"]:
                acted |= self.call(run, "POST", f"/statements/{st['id']}/approve", step="application_documents",
                                   json={"version": st["version"]["number"]}) is not None
        return acted

    def _details(self, run: Run, kind: str) -> bool:
        if kind in run.details_saved:
            return False
        run.details_saved.add(kind)
        keys = {"pack": ("email", "phone", "address_line", "city", "postcode", "country_of_residence"),
                "visa": ("email", "phone", "address_line", "city")}[kind]
        path = "/packs/details" if kind == "pack" else "/visa/details"
        return self.call(run, "PUT", path, json={"fields": {k: run.s.details[k] for k in keys}}) is not None

    # packs: details, the student's ticks, then approve the exact version when it is ready
    def _packs(self, run: Run, refs: list[str]) -> bool:
        acted = self._details(run, "pack")
        out = self.get(run, "/packs")
        if out is None:
            return acted
        for pack in out["programmes"]:
            ref = pack["programme_ref"]
            if ref not in refs:
                continue
            tickable = [i["key"] for i in pack["checklist"] if i.get("tickable") and i.get("state") != "ready"]
            if tickable and f"pack:{ref}" not in run.ticked:
                run.ticked.add(f"pack:{ref}")
                acted |= self.call(run, "PUT", f"/packs/{ref}/items", json={"tick": tickable}) is not None
                continue
            if pack["status"] == "ready" and not pack["approved"]:
                acted |= self.call(run, "POST", f"/packs/{ref}/approve", step="review_pack",
                                   json={"sha256": pack["manifest_sha256"]}) is not None
            elif pack["status"] in ("incomplete", "failed"):
                self._incomplete(run, f"pack:{ref}", "review_pack", pack)
        return acted

    def _incomplete(self, run: Run, key: str, step: str, pack: dict) -> None:
        """A pack or visa file that stays incomplete for 10 rehearsal days while its review waits is a failure."""
        if run.s.withhold and not run.released:
            return  # S5 holds a document back on purpose: its files cannot be complete yet
        today = clock.today()
        since = run.incomplete_since.setdefault(key, today)
        if (today - since).days >= 10:
            gaps = sorted(i["key"] for i in pack["checklist"] if i.get("state") not in ("ready", "manual"))
            sheet = sorted(r.get("key", "?") for r in pack["data_sheet"] if r.get("gap"))
            self.fail(f"incomplete:{run.s.sid}:{key.split(':')[0]}", run.s.sid, step,
                      "the file is complete once the student's material is in",
                      f"{pack['status']} for {(today - since).days} days; items {gaps}; data sheet gaps {sheet}")

    # applying: once every live programme's apply step waits with its pack approved, the student submits
    def _apply(self, run: Run, tasks: dict, by_template: dict) -> bool:
        live = sorted({t["programme_ref"] for k, t in tasks.items() if _template(k) in APPLY_STEPS
                       and t["state"] != "cancelled"})
        waiting = [t for template in APPLY_STEPS for t in by_template.get(template, [])]
        if not waiting:
            return False
        if "ready_to_submit" not in run.reached:
            packs = {p["programme_ref"]: p for p in (self.get(run, "/packs") or {"programmes": []})["programmes"]}
            ready = all(any(_template(k) in APPLY_STEPS and t["programme_ref"] == ref
                            and t["state"] == "waiting_student" for k, t in tasks.items())
                        and packs.get(ref, {}).get("approved") for ref in live)
            if not ready:
                return False
            run.reached.append("ready_to_submit")
            if run.s.event == "approved_changed" and not run.sop_changed:
                return self._change_sop(run)
        if run.s.event == "approved_changed" and run.sop_changed:
            if any(_template(k) == "review_pack" and t["state"] != "done" for k, t in tasks.items()):
                return False  # the changed pack is reviewed again before the student submits
        acted = False
        for t in waiting:  # "I submitted it": PAI OS never submits (invariant 5, 6)
            acted |= self._complete(run, t, {"submitted": True})
        return acted

    def _change_sop(self, run: Run) -> bool:
        """S9: a new version of the approved SOP, approved again, after every pack was approved."""
        run.sop_changed = True
        listed = self.get(run, "/statements", step="application_documents")
        sop = next((s for s in (listed or {"statements": []})["statements"]
                    if s["kind"] == "sop" and s["programme_ref"] is None), None)
        sop_id = sop["id"] if sop else run.sop_id  # if the page fails (logged), the id it showed before
        if sop_id is None:
            self.fail(f"no_sop:{run.s.sid}", run.s.sid, "application_documents", "an approved SOP", "none")
            return False
        addition = run.s.sop_addition or "I have added one more line."
        text_ = (sop["version"]["text"] + "\n\n" + addition) if sop and sop["version"] else addition
        r = self.call(run, "PUT", f"/statements/{sop_id}/text", step="application_documents", json={"text": text_})
        if r is None:
            return False
        self.call(run, "POST", f"/statements/{sop_id}/approve", step="application_documents",
                  json={"version": r.json()["version"]["number"]})
        self.get(run, "/packs")  # the student opens the packs: the changed ones are rebuilt
        return True

    # the visa file: choose the admitting programme, details, ticks, approve when ready
    def _visa(self, run: Run) -> bool:
        acted = False
        if "visa_choice" not in run.ticked:
            run.ticked.add("visa_choice")
            acted |= self.call(run, "PUT", "/visa/choice", json={"programme_ref": run.s.visa_programme}) is not None
        acted |= self._details(run, "visa")
        visa = self.get(run, "/visa")
        if visa is None or visa["status"] in ("no_choice", "building"):
            return acted
        tickable = [i["key"] for i in visa["checklist"] if i.get("tickable") and i.get("state") != "ready"]
        if tickable and "visa_items" not in run.ticked:
            run.ticked.add("visa_items")
            return self.call(run, "PUT", "/visa/items", json={"tick": tickable}) is not None or acted
        if visa["status"] == "ready" and not visa["approved"]:
            acted |= self.call(run, "POST", "/visa/approve", step="review_visa_file",
                               json={"sha256": visa["manifest_sha256"]}) is not None
        elif visa["status"] in ("incomplete", "failed") and "admission_letter" in run.uploads:
            self._incomplete(run, "visa:file", "review_visa_file", visa)
        return acted

    def _visa_ready(self, run: Run, tasks: dict) -> bool:
        step = tasks.get("visa_apply")
        if step is None:
            return False
        if step["state"] == "blocked" and (step["blocked_reason"] or "").startswith("fact_missing:") \
                and any(_template(k) == "review_visa_file" and t["state"] == "done" for k, t in tasks.items()):
            return self._supply_fact(run, step["blocked_reason"].split(":", 1)[1])
        if step["state"] != "waiting_student":
            return False
        if "visa_ready" not in run.reached:
            visa = self.get(run, "/visa")
            if visa is None or not visa["approved"]:
                return False
            run.reached.append("visa_ready")
            run.days = (clock.today() - self.start).days
        if self._events_open(run):
            return False  # the student keeps reading their inbox until the plan's events are answered
        run.state = "visa_ready"
        return True

    def _events_open(self, run: Run) -> bool:
        """Whether the plan still has a replan event without an answer, or a suggestion still pending (S11 ignores
        big ones: they must expire). The student stays in the loop until none is left. A paused plan's events wait for
        a person by design (S7-D9): they do not hold the student (the final check logs the pause)."""
        if self.svc.kernel.changes_paused(run.plan_id):
            return False
        if replan_events.pending(self.engine, TENANT, run.plan_id):
            return True
        return any(p.status == "pending" for p in self._proposals_of(run))

    def _supply_fact(self, run: Run, name: str) -> bool:
        """The admin step for a fact no source gives (today only visa_target_date): logged as a workaround."""
        if name != "visa_target_date" or name in self.admin_actions:
            if name != "visa_target_date":
                self.fail(f"fact_missing:{name}", "all", "visa_apply", f"{name} is known", "no value; no admin step")
            return False
        self.admin_actions.append(name)
        self.fail(f"fact_missing:{name}", "all", "visa_apply", "visa_apply waits for the student once the visa file "
                  "is approved", f"blocked on fact_missing:{name} (no source; the admin supplied a rehearsal value)",
                  "workaround")
        return self.call(None, "POST", "/facts", json={
            "scope": "route", "ref": ROUTE, "field": name, "intake_year": INTAKE["year"], "value": VISA_TARGET,
            "quote": "Rehearsal value supplied by the admin", "url": "https://rehearsal.example.invalid/visa",
            "status": "confirmed"}) is not None

    # ------------------------------------------------------------------ per loop: stuck

    def _observe(self, run: Run, today: date) -> None:
        plan = self._plan(run)
        inbox = self.get(run, "/inbox") or {"items": [], "proposals": []}
        fingerprint = (plan["revision"], plan["status"], tuple(sorted((t["instance_key"], t["state"])
                                                                      for t in plan["tasks"])))
        stuck = self.watch.see(run.s.sid, today, fingerprint, bool(inbox["items"] or inbox["proposals"]))
        if stuck is not None:
            self.failures.add(stuck)
            run.state = "stuck"

    # ------------------------------------------------------------------ step 4: the scripted events

    def _final(self, runs: list[Run]) -> None:
        for run in runs:
            if run.plan_id is None:
                continue
            self._safe(run, self._check_events)
            missing = [r for r in ("ready_to_submit", "visa_ready") if r not in run.reached]
            if self.check_finish and (missing or run.state != "visa_ready"):
                plan = self._plan(run)
                open_ = sorted(f"{_template(t['instance_key'])}:{t['state']}" for t in plan["tasks"]
                               if _live(t) and t["state"] not in ("done", "cancelled", "skipped")
                               and t["kind"] == "student")
                self.fail(f"not_finished:{run.s.sid}", run.s.sid, None, "ready to submit and visa file ready",
                          f"state {run.state}; not reached {missing}; open student steps {open_[:12]}")
                if run.state == "running":
                    run.state = "not_finished"
            if self.svc.kernel.changes_paused(run.plan_id):
                case = self._support_case(run)
                self.fail(f"paused:{run.s.sid}", run.s.sid, None, "the plan's automatic changes keep running",
                          f"changes paused at the end ({case['reason'] if case else 'no support case'}); "
                          f"{len(replan_events.pending(self.engine, TENANT, run.plan_id))} events wait for a person",
                          "workaround")
        self._integrity(runs)

    def _event(self, run: Run, name: str, ok: bool, step: str | None, expected: str, got: str) -> None:
        run.events[name] = "ok" if ok else "missed"
        if not ok:
            self.fail(f"missed:{run.s.sid}:{name}", run.s.sid, step, expected, got, "workaround")

    def _proposals_of(self, run: Run) -> list:
        PR = models.proposals
        with self.engine.connect() as conn:
            return conn.execute(select(PR).where(PR.c.plan_id == run.plan_id).order_by(PR.c.id)).all()

    def _check_events(self, run: Run) -> None:
        s, plan = run.s, self._plan(run)
        tasks = [t for t in plan["tasks"]]
        proposals = self._proposals_of(run)
        for field_, right in s.resolve.items():  # S2, S4: the mismatch is shown; the student confirms the right value
            profile = {v["key"]: v["value"] for v in (self.get(run, "/profile") or {"values": []})["values"]}
            shown = f"mismatch:{field_}" in run.findings_seen
            self._event(run, f"mismatch_{field_}", shown and str(profile.get(field_)) == str(right), None,
                        f"a mismatch on {field_} is shown and the right value confirmed",
                        f"shown {shown}; confirmed value matches {str(profile.get(field_)) == str(right)}")
        if s.event in ("rejected", "ignore_big"):
            [ref] = [r for r, v in s.admission.items() if v == "rejected"]
            big = [p for p in proposals if p.big and any(o["op"] in ("cancel_programme", "swap_programme")
                                                         and ref in (o.get("programme_ref"), o.get("out_ref"))
                                                         for o in p.ops)]
            mine = [t for t in tasks if t["programme_ref"] == ref and _live(t) and t["state"] in OPEN_STATES]
            open_ = [t["instance_key"] for t in mine if t["kind"] == "student"]
            if s.event == "rejected":
                ok = any(p.status == "accepted" for p in big) and not open_
                self._event(run, "rejected", ok, "admission_result",
                            "the rejecting programme is removed or swapped (a suggestion, accepted)",
                            f"suggestions {[p.status for p in big]}; open student steps of that programme {len(open_)}")
                left = sorted({f"{_template(t['instance_key'])}:{t['state']}" for t in mine if t["kind"] == "work"})
                if ok and left:
                    self.fail(f"left_open:{s.sid}:removed_programme", s.sid, "confirm_fact",
                              "removing a programme closes its open work (fact checks)",
                              f"{len(mine) - len(open_)} work steps of the removed programme stay open: {left}",
                              "workaround")
            else:
                ok = bool(big) and all(p.status == "expired" for p in big) and run.state == "visa_ready"
                self._event(run, "ignore_big", ok, "admission_result",
                            "the ignored big suggestion expires and the plan carries on",
                            f"suggestions {[p.status for p in big]}; state {run.state}")
        if s.event == "missing_document":
            key = s.withhold
            task_ids = [t["id"] for t in tasks if _template(t["instance_key"]) == key]
            with self.engine.connect() as conn:
                O = models.outbox
                rows = conn.execute(select(O.c.idempotency_key, O.c.template, O.c.created_at)).all()
            reminders = sorted(at for k, tpl, at in rows if tpl == "inbox_reminder"
                               and any(k.startswith(f"reminder:{i}:") and ":esc:" not in k for i in task_ids))
            asks = [p for p in proposals if p.status == "applied" and any(
                o["op"] == "request_from_student" and _template(o.get("instance_key", "")) == key for o in p.ops)]
            case = self._missing_case(run)
            with self.engine.connect() as conn:  # when the OS recorded each event (database time, in order)
                E = models.events
                event_at = dict(conn.execute(select(E.c.id, E.c.at).where(E.c.plan_id == run.plan_id)).all())
            ask = asks[0] if asks else None
            ask_at = min((event_at[i] for i in ask.event_ids if i in event_at), default=None) if ask else None
            case_at = min((event_at[i] for i in case["event_ids"] if i in event_at), default=None) if case else None
            in_order = bool(reminders and ask and case and ask_at and case_at
                            and reminders[0] < ask.created_at and ask_at < case_at)
            self._event(run, "missing_document", in_order, key,
                        "reminders by slack, then an ask, then a support case for the missing document",
                        f"reminders {len(reminders)}; asked {ask is not None}; missing-document case "
                        f"{case is not None}; in order {in_order}")
        if s.event == "late":
            E = models.events
            with self.engine.connect() as conn:
                risky = set(conn.execute(select(E.c.id).where(E.c.plan_id == run.plan_id,
                                                              E.c.type == "deadline_at_risk")).scalars().all())
            at_risk = [p for p in proposals if p.status == "applied" and set(p.event_ids) & risky
                       and any(o["op"] == "request_from_student" for o in p.ops)]
            moved = any(o["op"] == "reprioritise" for p in at_risk for o in p.ops)
            self._event(run, "late", bool(at_risk) and moved, None,
                        "the blocking student step moves ahead and is asked for",
                        f"asked {bool(at_risk)}; moved ahead {moved}")
        if s.event == "approved_changed":
            again = [t for t in tasks if _template(t["instance_key"]) == "review_pack" and "#" in t["instance_key"]
                     and CANCELLED_MARK not in t["instance_key"]]
            self._event(run, "approved_changed", bool(again) and run.sop_changed, "review_pack",
                        "the review step is added back",
                        f"SOP changed {run.sop_changed}; review steps added {len(again)}")

    def _integrity(self, runs: list[Run]) -> None:
        """Nothing lost or duplicated (9a gate 3): no work task left waiting for a worker; and `duplicates`."""
        T = models.tasks
        with self.engine.connect() as conn:
            lost = conn.execute(select(T.c.instance_key, T.c.state).where(
                T.c.kind == "work", T.c.state.in_(("ready", "running")))).all()
        if lost:
            self.fail("lost_tasks", "all", None, "no work task left ready or running",
                      f"{len(lost)}: {sorted({_template(k) + ':' + s for k, s in lost})[:8]}")
        for kind, found in duplicates(self.engine, {r.ref: r.drafts for r in runs}).items():
            self.fail(f"duplicate:{kind}", "all", None, DUPLICATE_CHECKS[kind], f"{len(found)}: {found[:6]}")

    # ------------------------------------------------------------------ step 5: the report

    def _report(self, runs: list[Run]) -> Report:
        students = {r.s.sid: StudentResult(state=r.state, events=[f"{k}:{v}" for k, v in sorted(r.events.items())],
                                           days=r.days, reached=list(r.reached)) for r in runs}
        return Report(students=students, failures=self.failures.counts(), kills=self.worker.kills if self.worker else 0,
                      admin_actions=list(self.admin_actions))
