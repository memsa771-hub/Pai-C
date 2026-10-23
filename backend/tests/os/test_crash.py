"""Crash test (spec §6 test 8): SIGKILL workers while a plan runs; no task is lost or duplicated.

The Spike 3 method on the production runner: three worker subprocesses with stable executor IDs,
a random one killed every 2 s and restarted with the same ID, so DBOS recovers what it left PENDING.
"""

import os
import random
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest
from dbos import DBOSClient
from sqlalchemy import func, select, text

from app.os import models
from app.os.compiler import compile_plan
from app.os.kernel import Kernel
from app.os.runner import APP_NAME, QUEUE_NAME
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.kernel_helpers import contract
from tests.os.runner_helpers import RUNS_DDL
from tests.os.test_runner import work_playbook

pytestmark = pytest.mark.chaos

BACKEND = Path(__file__).resolve().parents[2]
# 3 s tasks and a kill every 1.5 s: 20 tasks on 3 workers x 4 slots take >= 6 s, so >= 3 kills land in flight.
TASKS, WORKERS, KILL_EVERY_S, TIMEOUT_S, TASK_SLEEP_S = 20, 3, 1.5, 180.0, "3.0"


class Pool:
    def __init__(self, url: str, log_dir: Path, extra_env: dict | None = None) -> None:
        self.url, self.log_dir, self.extra_env = url, log_dir, extra_env or {}
        self.procs: dict[int, subprocess.Popen] = {}
        self.generation = {i: 0 for i in range(WORKERS)}
        self.labels: dict[int, str] = {}

    def start(self, slot: int) -> None:
        label = f"w{slot}g{self.generation[slot]}"
        self.generation[slot] += 1
        env = {**os.environ, "OS_DATABASE_URL": self.url, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
               "OS_WORKER_ID": f"crash-w{slot}", "OS_EXTRA_MODULES": "tests.os.runner_helpers:SLEEP_MODULE",
               "OS_PARENT_PID": str(os.getpid()), "OS_TEST_LABEL": label, "OS_TEST_SLEEP_S": TASK_SLEEP_S,
               **self.extra_env}
        log = open(self.log_dir / f"{label}.log", "wb")
        self.procs[slot] = subprocess.Popen([sys.executable, "-m", "app.os.runner.worker"], cwd=BACKEND, env=env,
                                            stdout=log, stderr=subprocess.STDOUT)
        self.labels[slot] = label

    def kill(self, slot: int) -> str:
        proc, label = self.procs[slot], self.labels[slot]
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        return label

    def stop_all(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in self.procs.values():
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _wait_queue(client: DBOSClient, pool: Pool) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if client.retrieve_queue(QUEUE_NAME) is not None:
                return
        except Exception:  # DBOS system tables not created yet
            pass
        for slot, proc in pool.procs.items():
            assert proc.poll() is None, f"worker {pool.labels[slot]} exited during startup"
        time.sleep(0.2)
    raise TimeoutError("no worker registered the queue")


def test_worker_enqueues_by_itself(os_db, engine, clean, tmp_path):
    """Review I1: production has no test loop calling enqueue_pending; the worker must send requests itself."""
    reset_dbos_schema(os_db)
    pool = Pool(os_db, tmp_path)
    client = None
    try:
        pool.start(0)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        kernel = Kernel(engine, "pai")
        draft = compile_plan(contract(), work_playbook("system.milestone", 3), {}, {}, date(2027, 3, 1))
        plan_id = kernel.create_plan(contract(), draft).plan_id
        deadline = time.monotonic() + 30  # far below the 5-minute reconciler period
        while True:
            with engine.connect() as conn:
                states = conn.execute(select(models.tasks.c.state).where(models.tasks.c.plan_id == plan_id)
                                      ).scalars().all()
            if states == ["done"] * 3:
                break
            assert time.monotonic() < deadline, f"tasks not picked up by the worker: {states} (logs: {tmp_path})"
            time.sleep(0.3)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()


def test_crash_no_lost_or_duplicated(os_db, engine, clean, tmp_path):
    reset_dbos_schema(os_db)
    with engine.begin() as conn:
        conn.execute(text(RUNS_DDL))
        conn.execute(text("TRUNCATE public.os_test_runs"))
    kernel = Kernel(engine, "pai")
    pool = Pool(os_db, tmp_path)
    rng = random.Random(7)
    kills: list[tuple[str, object]] = []  # (label, db time after the process was reaped)
    client = None
    try:
        for slot in range(WORKERS):
            pool.start(slot)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        draft = compile_plan(contract(), work_playbook("test.sleep", TASKS), {}, {}, date(2027, 3, 1))
        plan_id = kernel.create_plan(contract(), draft).plan_id  # the workers enqueue it themselves (I1)
        deadline = time.monotonic() + TIMEOUT_S
        next_kill = time.monotonic() + KILL_EVERY_S
        while True:
            with engine.connect() as conn:
                open_n = conn.execute(select(func.count()).select_from(models.tasks).where(
                    models.tasks.c.plan_id == plan_id, models.tasks.c.state != "done")).scalar_one()
            if open_n == 0:
                break
            assert time.monotonic() < deadline, f"{open_n} tasks still open after {TIMEOUT_S}s (logs: {tmp_path})"
            if time.monotonic() >= next_kill:
                slot = rng.randrange(WORKERS)
                label = pool.kill(slot)
                with engine.connect() as conn:
                    kills.append((label, conn.execute(text("SELECT clock_timestamp()")).scalar_one()))
                pool.start(slot)
                next_kill = time.monotonic() + KILL_EVERY_S
            time.sleep(0.2)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()

    with engine.connect() as conn:
        runs = conn.execute(text(
            "SELECT task_id, attempt, label, at FROM public.os_test_runs ORDER BY task_id, attempt, at")).all()
        attempts = conn.execute(select(func.count()).select_from(models.task_attempts)).scalar_one()
        states = conn.execute(select(models.tasks.c.state).where(models.tasks.c.plan_id == plan_id)).scalars().all()

    assert states == ["done"] * TASKS
    assert len(kills) >= 3
    assert attempts == TASKS  # one attempt per task: nothing was retried as a new attempt
    by_attempt: dict[tuple, list] = {}
    for r in runs:
        by_attempt.setdefault((r.task_id, r.attempt), []).append(r)
    assert set(by_attempt) == {(t, 1) for t, _ in by_attempt}  # every run was attempt 1
    assert len(by_attempt) == TASKS
    for rows in by_attempt.values():  # a re-run is legitimate only after the earlier run's worker was killed
        for earlier, later in zip(rows, rows[1:]):
            assert any(label == earlier.label and earlier.at <= t <= later.at for label, t in kills), \
                f"duplicate run of task {earlier.task_id} without a kill of {earlier.label}"


def test_crash_during_research(os_db, engine, clean, tmp_path):
    """Slice 2 spec §8 test 6: SIGKILL workers during research (fake model). No lost task, no duplicate
    os_agent_runs row, no duplicate fact or fact_changed event."""
    from datetime import datetime, timezone

    from sqlalchemy import insert

    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.knowledge.programmes import Programme, ProgrammeStore
    from app.os.playbooks import load_playbook_dir
    from app.os.service import PlanService
    from app.os.settings import load_settings
    from tests.os.research_helpers import PAGES, page_text
    from tests.os.test_golden import TEST_STUDENT

    reset_dbos_schema(os_db)
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    store = ProgrammeStore(engine, "pai")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:  # the pages are already in the gateway's cache: no network in the workers
        for ref, (url, domain, name) in PAGES.items():
            store.upsert(Programme(ref=ref, route_key="germany_master", university="University", name=name,
                                   aliases=(), start_urls=(url,), official_domains=(domain,)))
            conn.execute(insert(models.pages).values(tenant_id="pai", url=url, final_url=url, http_status=200,
                                                     text=page_text(name), links=[], fetched_at=now))
    service = PlanService(engine, load_settings({"DATABASE_URL": os_db}), Kernel(engine, "pai"), kb,
                          load_playbook_dir(), today=lambda: date.today())
    pool = Pool(os_db, tmp_path, {"OS_TEST_RESEARCH_MODEL": "tests.os.research_helpers:slow_model",
                                  "OS_TEST_MODEL_SLEEP_S": "1.5"})
    rng = random.Random(11)
    kills = 0
    client = None
    keys = [f"confirm_fact@{ref}:{field}" for ref in PAGES for field in ("deadline_close", "application_route")]
    try:
        for slot in range(2):
            pool.start(slot)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        plan_id = service.start_plan(TEST_STUDENT).plan_id  # the workers run the confirm tasks, then research
        deadline = time.monotonic() + TIMEOUT_S
        next_kill = time.monotonic() + KILL_EVERY_S
        while True:
            with engine.connect() as conn:
                states = conn.execute(select(models.tasks.c.state).where(
                    models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key.in_(keys))).scalars().all()
                runs = conn.execute(select(models.research_runs.c.status)).scalars().all()
            if len(states) == len(keys) and set(states) == {"done"} and len(runs) == 3 and set(runs) == {"done"}:
                break
            assert time.monotonic() < deadline, f"stuck: tasks {states}, runs {runs} (logs: {tmp_path})"
            if time.monotonic() >= next_kill and kills < 6:
                slot = rng.randrange(2)
                pool.kill(slot)
                kills += 1
                pool.start(slot)
                next_kill = time.monotonic() + KILL_EVERY_S
            time.sleep(0.2)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()

    with engine.connect() as conn:
        agent_runs = conn.execute(select(models.agent_runs.c.research_run_id, models.agent_runs.c.reading)).all()
        facts = conn.execute(select(models.knowledge_facts.c.ref, models.knowledge_facts.c.status,
                                    models.knowledge_facts.c.source).where(
            models.knowledge_facts.c.field == "deadline_close", models.knowledge_facts.c.ref.in_(list(PAGES)))).all()
        changed = conn.execute(select(models.events.c.payload).where(models.events.c.type == "fact_changed")).scalars().all()
    assert kills >= 2
    assert len(agent_runs) == len(set(agent_runs)) == 6  # A and B per programme, once each
    assert sorted(f.ref for f in facts) == sorted(PAGES) and {(f.status, f.source) for f in facts} == {("confirmed", "research")}
    per_fact = [(e["ref"], e["field"]) for e in changed if e["field"] == "deadline_close"]
    assert sorted(per_fact) == sorted((ref, "deadline_close") for ref in PAGES)  # one event per change, never repeated


def test_crash_during_document_read(os_db, engine, clean, tmp_path):
    """Slice 3 spec §8 test 6: SIGKILL workers while documents are read (fake model). Every upload ends read, with
    one os_agent_runs row, one row per field and one set of findings: nothing lost, nothing duplicated."""
    import io

    from PIL import Image

    from app.os.documents.run import enqueue_document
    from app.os.documents.store import DocumentStore, FindingStore
    from app.os.documents.types import load_document_types

    reset_dbos_schema(os_db)
    t = load_document_types()["transcript"]
    docs = DocumentStore(engine, "pai")
    ids = []
    for n in range(12):  # synthetic images; they agree, so no finding. Two waves on 2 workers x 4 slots
        out = io.BytesIO()
        Image.new("RGB", (400, 560), (n * 20, 200, 200)).save(out, "JPEG")
        ids.append(docs.create("crash-student", "transcript", t.version, f"t{n}.jpg", "image/jpeg", out.getvalue()))
    pool = Pool(os_db, tmp_path, {"OS_TEST_DOCUMENT_MODEL": "tests.os.document_helpers:slow_model",
                                  "OS_TEST_MODEL_SLEEP_S": "1.5"})
    rng = random.Random(13)
    kills = 0
    client = None
    try:
        for slot in range(2):
            pool.start(slot)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        for doc_id in ids:
            enqueue_document(client, "pai", docs.get(doc_id))
        deadline = time.monotonic() + TIMEOUT_S
        next_kill = time.monotonic() + KILL_EVERY_S
        while True:
            statuses = [docs.get(i).status for i in ids]
            if set(statuses) == {"read"}:
                break
            assert time.monotonic() < deadline, f"stuck: {statuses} (logs: {tmp_path})"
            if time.monotonic() >= next_kill and kills < 6:
                slot = rng.randrange(2)
                pool.kill(slot)
                kills += 1
                pool.start(slot)
                next_kill = time.monotonic() + KILL_EVERY_S
            time.sleep(0.2)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()

    with engine.connect() as conn:
        agent_runs = conn.execute(select(models.agent_runs.c.document_id, models.agent_runs.c.reading)).all()
        fields = conn.execute(select(models.document_fields.c.document_id, models.document_fields.c.field)).all()
    assert kills >= 2
    assert sorted(r.document_id for r in agent_runs) == sorted(ids) and len(set(agent_runs)) == len(ids)
    assert len(fields) == len(set(fields)) == len(ids) * len(t.fields)  # one row per field, never repeated
    assert FindingStore(engine, "pai").list_open("crash-student") == []


def test_crash_during_pack_build(os_db, engine, clean, tmp_path):
    """Slice 6a spec §8 test 6: SIGKILL workers while packs are rendered. Every pack ends built, with exactly one
    version and one stored file per item: nothing lost, nothing duplicated."""
    import io

    from PIL import Image

    from app.os.artifacts.store import ArtifactStore
    from app.os.documents.store import DocumentStore
    from app.os.knowledge import SqlKnowledge
    from app.os.packs.config import load_pack_configs
    from app.os.packs.inputs import inputs_sha, load_inputs
    from app.os.packs.run import enqueue_pack
    from app.os.playbooks import load_playbook_dir
    from app.os.statements.config import load_statement_configs

    reset_dbos_schema(os_db)
    route, programme, year = "germany_master", "ovgu-eeit", 2027
    cfg = load_pack_configs()[route]
    book = next(b for (k, _), b in load_playbook_dir().items() if k == route)
    stmt, kb = load_statement_configs().get(route), SqlKnowledge(engine, "pai")
    docs, arts = DocumentStore(engine, "pai"), ArtifactStore(engine, "pai")
    doc_items = [i for i in cfg.checklist if i.kind == "document"]
    students = [f"crash-student-{n}" for n in range(8)]
    for s in students:  # synthetic noisy scans, so each conversion takes real time and kills land inside one
        for item in doc_items:
            out = io.BytesIO()
            Image.frombytes("RGB", (1600, 2000), os.urandom(1600 * 2000 * 3)).save(out, "JPEG", quality=90)
            docs.set_status(docs.create(s, item.ref, 1, f"{item.ref}.jpg", "image/jpeg", out.getvalue()), "confirmed")
        for kind in ("sop", "cv"):
            a = arts.get_or_create(s, kind, None)
            arts.approve(a.id, arts.add_version(a.id, f"A fictional {kind}.", "student").number)
    pool = Pool(os_db, tmp_path)
    rng = random.Random(17)
    kills = 0
    client = None
    try:
        for slot in range(2):
            pool.start(slot)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        for s in students:
            sha = inputs_sha(load_inputs(engine, "pai", kb, book, cfg, stmt, s, programme, year))
            enqueue_pack(client, "pai", s, programme, route, year, sha)
        deadline = time.monotonic() + TIMEOUT_S
        next_kill = time.monotonic() + KILL_EVERY_S
        while True:
            packs = [a for s in students for a in arts.list_for(s) if a.kind == "pack"]
            statuses = [a.status for a in packs]
            if len(packs) == len(students) and set(statuses) <= {"ready", "incomplete"}:
                break
            assert time.monotonic() < deadline, f"stuck: {statuses} (logs: {tmp_path})"
            if time.monotonic() >= next_kill and kills < 6:
                slot = rng.randrange(2)
                pool.kill(slot)
                kills += 1
                pool.start(slot)
                next_kill = time.monotonic() + KILL_EVERY_S
            time.sleep(0.2)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()

    assert kills >= 2
    for a in packs:
        assert len(arts.versions(a.id)) == 1, a  # one manifest version per inputs
    with engine.connect() as conn:
        files = conn.execute(select(models.pack_files.c.student_ref, models.pack_files.c.item_key)).all()
    per_student = len(doc_items) + 3  # each document, the data sheet, the SOP and the CV
    assert len(files) == len(set(files)) == len(students) * per_student


def test_crash_during_visa_build(os_db, engine, clean, tmp_path):
    """Slice 6b plan Task 7: SIGKILL workers while visa files are rendered. Every visa file ends built, with exactly
    one version and one stored file per item: nothing lost, nothing duplicated."""
    import io

    from PIL import Image

    from app.os.artifacts.store import ArtifactStore
    from app.os.documents.store import DocumentStore
    from app.os.knowledge import SqlKnowledge
    from app.os.packs.config import load_pack_configs
    from app.os.packs.inputs import inputs_sha, load_inputs
    from app.os.packs.run import enqueue_pack
    from app.os.packs.visa import VisaChoiceStore
    from app.os.playbooks import load_playbook_dir

    reset_dbos_schema(os_db)
    route, programme, year = "germany_master", "ovgu-eeit", 2027
    cfg = load_pack_configs(kind="visa")[route]
    book = next(b for (k, _), b in load_playbook_dir().items() if k == route)
    kb = SqlKnowledge(engine, "pai")
    docs, arts, choices = DocumentStore(engine, "pai"), ArtifactStore(engine, "pai"), VisaChoiceStore(engine, "pai")
    doc_items = [i for i in cfg.checklist if i.kind == "document"]
    students = [f"crash-student-{n}" for n in range(8)]
    for s in students:  # synthetic noisy scans, so each conversion takes real time and kills land inside one
        for item in doc_items:
            out = io.BytesIO()
            Image.frombytes("RGB", (1600, 2000), os.urandom(1600 * 2000 * 3)).save(out, "JPEG", quality=90)
            docs.set_status(docs.create(s, item.ref, 1, f"{item.ref}.jpg", "image/jpeg", out.getvalue()), "confirmed")
        for kind in ("sop", "cv"):
            a = arts.get_or_create(s, kind, None)
            arts.approve(a.id, arts.add_version(a.id, f"A fictional {kind}.", "student").number)
        choices.set_programme(s, programme)
    pool = Pool(os_db, tmp_path)
    rng = random.Random(19)
    kills = 0
    client = None
    try:
        for slot in range(2):
            pool.start(slot)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        for s in students:
            sha = inputs_sha(load_inputs(engine, "pai", kb, book, cfg, None, s, programme, year, "visa"))
            enqueue_pack(client, "pai", s, programme, route, year, sha, kind="visa")
        deadline = time.monotonic() + TIMEOUT_S
        next_kill = time.monotonic() + KILL_EVERY_S
        while True:
            files_ = [a for s in students for a in arts.list_for(s) if a.kind == "visa"]
            statuses = [a.status for a in files_]
            if len(files_) == len(students) and set(statuses) <= {"ready", "incomplete"}:
                break
            assert time.monotonic() < deadline, f"stuck: {statuses} (logs: {tmp_path})"
            if time.monotonic() >= next_kill and kills < 6:
                slot = rng.randrange(2)
                pool.kill(slot)
                kills += 1
                pool.start(slot)
                next_kill = time.monotonic() + KILL_EVERY_S
            time.sleep(0.2)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()

    assert kills >= 2
    for a in files_:
        assert len(arts.versions(a.id)) == 1, a  # one manifest version per inputs
    with engine.connect() as conn:
        files = conn.execute(select(models.pack_files.c.student_ref, models.pack_files.c.item_key)).all()
    per_student = len(doc_items) + 3  # each document, the data sheet, the motivation letter (the SOP) and the CV
    assert len(files) == len(set(files)) == len(students) * per_student


def test_crash_during_replan(os_db, engine, clean, tmp_path):
    """Slice 7 spec §8: SIGKILL workers while replans run. Every event ends with exactly one proposal, one override
    and one replan revision: nothing lost, nothing duplicated."""
    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.playbooks import load_playbook_dir
    from app.os.replan import events
    from app.os.replan.run import enqueue_replan
    from app.os.service import PlanService
    from app.os.settings import load_settings
    from tests.os.test_golden import TEST_STUDENT

    reset_dbos_schema(os_db)
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb, load_playbook_dir(),
                      today=lambda: date(2027, 2, 1))
    plan_ids, event_ids = [], []
    for n in range(8):
        c = TEST_STUDENT.model_copy(update={"external_ref": f"crash-{n}", "student_ref": f"crash-student-{n}"})
        plan_id = svc.start_plan(c).plan_id
        with engine.begin() as conn:
            event_ids.append(events.record(conn, "pai", plan_id, "approved_changed",
                                           {"template_key": "review_visa_file", "programme_ref": None}, f"crash-{n}"))
        plan_ids.append(plan_id)
    pool = Pool(os_db, tmp_path)
    rng = random.Random(23)
    kills = 0
    client = None
    PR, O, REV = models.proposals, models.plan_overrides, models.plan_revisions
    try:
        for slot in range(2):
            pool.start(slot)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)
        for plan_id, eid in zip(plan_ids, event_ids):
            enqueue_replan(client, "pai", plan_id, eid)
        deadline = time.monotonic() + TIMEOUT_S
        next_kill = time.monotonic() + KILL_EVERY_S
        while True:
            with engine.connect() as conn:
                done = conn.execute(select(func.count()).select_from(PR).where(
                    PR.c.status == "applied", PR.c.revision.is_not(None))).scalar()
            if done == len(plan_ids):
                break
            assert time.monotonic() < deadline, f"stuck: {done} of {len(plan_ids)} (logs: {tmp_path})"
            if time.monotonic() >= next_kill and kills < 6:
                slot = rng.randrange(2)
                pool.kill(slot)
                kills += 1
                pool.start(slot)
                next_kill = time.monotonic() + KILL_EVERY_S
            time.sleep(0.2)
    finally:
        pool.stop_all()
        if client is not None:
            client.destroy()

    assert kills >= 2
    with engine.connect() as conn:
        for plan_id in plan_ids:
            assert conn.execute(select(func.count()).select_from(PR).where(PR.c.plan_id == plan_id)).scalar() == 1
            assert conn.execute(select(func.count()).select_from(O).where(O.c.plan_id == plan_id)).scalar() == 1
            assert conn.execute(select(func.count()).select_from(REV).where(
                REV.c.plan_id == plan_id, REV.c.cause.like("replan:%"))).scalar() == 1
