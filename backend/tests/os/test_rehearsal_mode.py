"""Slice 9a Task 3: rehearsal mode (stored offset, advance, tick). Spec §2.2; plan Review Focus 1 and 2."""

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.os import clock, models
from app.os.api import build_router, make_services
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema

FAKE = Path(__file__).parent / "playbooks"
TOKEN = "test-admin-token"
ADMIN = {"X-OS-Admin-Token": TOKEN}
BASE = "/v1/os/admin/rehearsal"
DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def real_clock():
    clock.configure(None)
    yield
    clock.configure(None)


def _settings(os_db: str, rehearsal: bool, **extra: str):
    env = {"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true",
           "OS_REHEARSAL": "true" if rehearsal else "", **extra}
    return load_settings(env)


class FakeClient:
    """Stands in for the API's DBOSClient: records enqueues; answers status from `statuses`."""

    def __init__(self):
        self.enqueued: list[dict] = []
        self.statuses: dict[str, SimpleNamespace] = {}

    def enqueue(self, options, *args):
        self.enqueued.append(dict(options))

    def list_workflows(self, *, workflow_ids=None, name=None, **_):
        return [s for wid, s in self.statuses.items() if wid in (workflow_ids or []) and s.name == name]


def _app(engine, settings, client=None) -> TestClient:
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE),
                             today=lambda: date(2027, 3, 1), dbos_client=lambda: client)
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    return TestClient(app)


def _near(a: datetime, b: datetime) -> bool:
    return abs(a - b) < timedelta(seconds=30)


# ---- the stored offset -------------------------------------------------------------------------------------------

def test_advance_moves_now(engine, clean, os_db):
    from app.os.rehearsal.store import ClockStore, install_clock

    install_clock(_settings(os_db, True), engine)
    assert ClockStore(engine, "pai").advance(10) == 10 * DAY
    assert _near(clock.now(), datetime.now(timezone.utc) + 10 * DAY)


def test_concurrent_advance_adds_both(engine, clean):
    from app.os.rehearsal.store import ClockStore

    start, errors = threading.Barrier(2), []

    def advance():
        try:
            start.wait(timeout=10)
            ClockStore(engine, "pai").advance(5)  # each thread takes its own pooled connection
        except Exception as e:  # noqa: BLE001  (reported below)
            errors.append(e)

    threads = [threading.Thread(target=advance) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert ClockStore(engine, "pai").offset() == 10 * DAY


def test_offset_ignored_when_rehearsal_off(engine, clean, os_db):
    from app.os.rehearsal.store import install_clock

    with engine.begin() as conn:
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="pai", offset_seconds=30 * 86400))
    install_clock(_settings(os_db, False), engine)
    assert _near(clock.now(), datetime.now(timezone.utc))
    _app(engine, _settings(os_db, False))  # the API path (make_services) too
    assert _near(clock.now(), datetime.now(timezone.utc))


def test_offset_is_per_tenant(engine, clean):
    from app.os.rehearsal.store import ClockStore

    ClockStore(engine, "other").advance(3)
    assert ClockStore(engine, "pai").offset() == timedelta(0)
    assert ClockStore(engine, "other").offset() == 3 * DAY


# ---- the calls -----------------------------------------------------------------------------------------------------

def test_rehearsal_calls_404_when_off(engine, clean, os_db):
    api = _app(engine, _settings(os_db, False), FakeClient())
    assert api.post(f"{BASE}/advance", json={"days": 1}, headers=ADMIN).status_code == 404
    assert api.post(f"{BASE}/tick", headers=ADMIN).status_code == 404
    assert api.get(f"{BASE}/tick/anything", headers=ADMIN).status_code == 404


def test_advance_bounds(engine, clean, os_db):
    api = _app(engine, _settings(os_db, True), FakeClient())
    assert api.post(f"{BASE}/advance", json={"days": 0}, headers=ADMIN).status_code == 422
    assert api.post(f"{BASE}/advance", json={"days": 61}, headers=ADMIN).status_code == 422
    one = api.post(f"{BASE}/advance", json={"days": 1}, headers=ADMIN)
    assert one.status_code == 200
    assert one.json()["offset_days"] == 1.0
    sixty = api.post(f"{BASE}/advance", json={"days": 60}, headers=ADMIN)
    assert sixty.status_code == 200
    assert sixty.json()["offset_days"] == 61.0
    moved = datetime.fromisoformat(sixty.json()["now"])
    assert _near(moved, datetime.now(timezone.utc) + 61 * DAY)


def test_advance_needs_admin(engine, clean, os_db):
    api = _app(engine, _settings(os_db, True), FakeClient())
    assert api.post(f"{BASE}/advance", json={"days": 1}).status_code == 401
    assert api.post(f"{BASE}/advance", json={"days": 1}, headers={"X-OS-Admin-Token": "wrong"}).status_code == 401
    assert api.post(f"{BASE}/tick").status_code == 401
    assert api.get(f"{BASE}/tick/x").status_code == 401


def test_tick_route_enqueues_and_reports(engine, clean, os_db):
    from app.os.rehearsal.tick import TICK_WORKFLOW

    fake = FakeClient()
    api = _app(engine, _settings(os_db, True), fake)
    sent = api.post(f"{BASE}/tick", headers=ADMIN)
    assert sent.status_code == 200
    tick_id = sent.json()["tick_id"]
    assert [(o["workflow_name"], o["workflow_id"], o["queue_name"]) for o in fake.enqueued] == [
        (TICK_WORKFLOW, tick_id, "os")]
    assert api.get(f"{BASE}/tick/{tick_id}", headers=ADMIN).status_code == 404  # not in DBOS yet
    finished = {"ran": ["reminders"], "failed": []}
    some_failed = {"ran": ["reminders"], "failed": ["replan"]}
    for status, output, want in (("ENQUEUED", None, {"status": "running", "ran": [], "failed": []}),
                                 ("PENDING", None, {"status": "running", "ran": [], "failed": []}),
                                 ("SUCCESS", finished, {"status": "done", **finished}),
                                 ("SUCCESS", some_failed, {"status": "error", **some_failed}),
                                 ("ERROR", None, {"status": "error", "ran": [], "failed": []}),
                                 ("CANCELLED", None, {"status": "error", "ran": [], "failed": []})):
        fake.statuses[tick_id] = SimpleNamespace(status=status, name=TICK_WORKFLOW, output=output)
        assert api.get(f"{BASE}/tick/{tick_id}", headers=ADMIN).json() == want
    fake.statuses["other"] = SimpleNamespace(status="SUCCESS", name="os.research", output="secret")
    assert api.get(f"{BASE}/tick/other", headers=ADMIN).status_code == 404  # only tick workflows are shown


# ---- the tick -------------------------------------------------------------------------------------------------------

def test_tick_runs_jobs_in_order():
    from app.os.rehearsal.tick import JOB_ORDER, run_tick

    assert JOB_ORDER == ("deadline_engine", "reminders", "replan", "deliver_outbox", "freshness", "documents_retry",
                         "reconcile")
    seen: list[str] = []
    jobs = {name: (lambda n=name: seen.append(n)) for name in reversed(JOB_ORDER)}
    jobs["counsellor_intake"] = lambda: seen.append("counsellor_intake")  # not in JOB_ORDER: never ticked
    del jobs["documents_retry"]  # a job this worker does not have is skipped
    result = run_tick(jobs)
    want = [n for n in JOB_ORDER if n != "documents_retry"]
    assert seen == want
    assert result == {"ran": want, "failed": []}


def test_tick_runs_every_job_when_one_fails(caplog):
    from app.os.rehearsal.tick import JOB_ORDER, run_tick

    seen: list[str] = []

    def broken():
        raise RuntimeError("replan is broken")

    jobs = {name: (lambda n=name: seen.append(n)) for name in JOB_ORDER}
    jobs["replan"] = broken  # an early job fails: the later ones (deliver_outbox, reconcile, ...) still run
    caplog.set_level(logging.ERROR)
    result = run_tick(jobs)
    rest = [n for n in JOB_ORDER if n != "replan"]
    assert seen == rest
    assert result == {"ran": rest, "failed": ["replan"]}
    assert any("replan" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)


def test_tick_of_another_tenant_is_404(engine, clean, os_db):
    from app.os.rehearsal.tick import TICK_WORKFLOW

    fake = FakeClient()
    pai_tick = "rehearsal-tick:pai:0123abcd"
    fake.statuses[pai_tick] = SimpleNamespace(status="SUCCESS", name=TICK_WORKFLOW, output={"ran": [], "failed": []})
    other = _app(engine, _settings(os_db, True, OS_TENANT_ID="other"), fake)
    assert other.get(f"{BASE}/tick/{pai_tick}", headers=ADMIN).status_code == 404
    pai = _app(engine, _settings(os_db, True), fake)
    assert pai.get(f"{BASE}/tick/{pai_tick}", headers=ADMIN).status_code == 200


def test_tick_workflow_runs_on_dbos(engine, clean, os_db):
    """The real path: the API enqueues os.rehearsal_tick on the queue, a DBOS worker runs it, the API reads it."""
    from dbos import DBOS, DBOSClient

    from app.os.kernel import Kernel
    from app.os.rehearsal.tick import register_tick
    from app.os.runner import (
        APP_NAME,
        dbos_config,
        default_registry,
        launch,
        register_workflow,
    )

    reset_dbos_schema(os_db)
    settings = _settings(os_db, True, OS_DBOS_SYSTEM_SCHEMA=TEST_DBOS_SCHEMA)
    seen: list[str] = []
    DBOS(config=dbos_config(settings, "tick-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, "pai"))

    def broken():
        raise RuntimeError("replan is broken")

    register_tick({"reconcile": lambda: seen.append("reconcile"), "reminders": lambda: seen.append("reminders"),
                   "replan": broken})
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    try:
        api = _app(engine, settings, client)
        tick_id = api.post(f"{BASE}/tick", headers=ADMIN).json()["tick_id"]
        deadline = time.monotonic() + 60  # the broken step is retried (STEP_CONFIG) before it counts as failed
        while (got := api.get(f"{BASE}/tick/{tick_id}", headers=ADMIN).json())["status"] == "running":
            assert time.monotonic() < deadline, "the tick never finished"
            time.sleep(0.2)
        assert got == {"status": "error", "ran": ["reminders", "reconcile"], "failed": ["replan"]}
        assert seen == ["reminders", "reconcile"]
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


# ---- the worker and startup -----------------------------------------------------------------------------------------

def _build(monkeypatch, settings):
    from dbos import DBOS

    from app.os.runner import worker

    jobs, ticks = [], []
    monkeypatch.setattr(worker, "register_job", lambda name, cron, fn: jobs.append((name, cron)))
    monkeypatch.setattr(worker, "register_tick", lambda found: ticks.append(sorted(found)))
    for var in ("OS_TEST_RESEARCH_MODEL", "OS_TEST_DOCUMENT_MODEL", "OS_TEST_STATEMENT_MODEL", "OS_TEST_REPLAN_MODEL",
                "OS_EXTRA_MODULES"):
        monkeypatch.delenv(var, raising=False)
    try:
        _, _, client, _ = worker.build(settings)
        client.destroy()
    finally:
        DBOS.destroy(destroy_registry=True)
    return jobs, ticks


TODAY_SCHEDULES = [("reconcile", "*/5 * * * *"), ("deadline_engine", "0 * * * *"), ("reminders", "0 * * * *"),
                   ("deliver_outbox", "* * * * *"), ("freshness", "0 3 * * *"), ("replan", "*/5 * * * *"),
                   ("counsellor_intake", "* * * * *")]


def test_worker_registers_no_cron_in_rehearsal(monkeypatch, os_db):
    jobs, ticks = _build(monkeypatch, _settings(os_db, True, OS_WORKER_ID="w1"))
    assert jobs == []
    assert ticks == [sorted(name for name, _ in TODAY_SCHEDULES)]

    jobs, ticks = _build(monkeypatch, _settings(os_db, False, OS_WORKER_ID="w1"))
    assert jobs == TODAY_SCHEDULES
    assert ticks == []


def test_startup_warns_in_rehearsal(monkeypatch, engine, clean, os_db, caplog):
    caplog.set_level(logging.WARNING)
    _app(engine, _settings(os_db, True))
    api_warned = [r for r in caplog.records if r.levelno == logging.WARNING and "REHEARSAL MODE" in r.getMessage()]
    assert api_warned
    caplog.clear()
    _build(monkeypatch, _settings(os_db, True, OS_WORKER_ID="w1"))
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "REHEARSAL MODE" in r.getMessage()]
    caplog.clear()
    _app(engine, _settings(os_db, False))
    assert not [r for r in caplog.records if "REHEARSAL MODE" in r.getMessage()]


def test_settings_reads_rehearsal():
    base = {"DATABASE_URL": "postgresql://x/y"}
    assert load_settings(base).rehearsal is False
    for word in ("1", "true", "yes", "on", " ON "):
        assert load_settings({**base, "OS_REHEARSAL": word}).rehearsal is True
    assert load_settings({**base, "OS_REHEARSAL": "off"}).rehearsal is False


def test_worker_refuses_two_jobs_with_one_name(monkeypatch, os_db):
    from app.os.runner import worker

    monkeypatch.setattr(worker, "JOB_FACTORIES", [("reminders", "0 * * * *", lambda *a: (lambda: None))])
    with pytest.raises(ValueError, match="reminders"):
        _build(monkeypatch, _settings(os_db, True, OS_WORKER_ID="w1"))
