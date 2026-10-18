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
from app.os.runner import APP_NAME, QUEUE_NAME, enqueue_pending, reconcile
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.kernel_helpers import contract
from tests.os.runner_helpers import RUNS_DDL
from tests.os.test_runner import work_playbook

pytestmark = pytest.mark.chaos

BACKEND = Path(__file__).resolve().parents[2]
# 3 s tasks and a kill every 1.5 s: 20 tasks on 3 workers x 4 slots take >= 6 s, so >= 3 kills land in flight.
TASKS, WORKERS, KILL_EVERY_S, TIMEOUT_S, TASK_SLEEP_S = 20, 3, 1.5, 180.0, "3.0"


class Pool:
    def __init__(self, url: str, log_dir: Path) -> None:
        self.url, self.log_dir = url, log_dir
        self.procs: dict[int, subprocess.Popen] = {}
        self.generation = {i: 0 for i in range(WORKERS)}
        self.labels: dict[int, str] = {}

    def start(self, slot: int) -> None:
        label = f"w{slot}g{self.generation[slot]}"
        self.generation[slot] += 1
        env = {**os.environ, "OS_DATABASE_URL": self.url, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
               "OS_WORKER_ID": f"crash-w{slot}", "OS_EXTRA_MODULES": "tests.os.runner_helpers:SLEEP_MODULE",
               "OS_PARENT_PID": str(os.getpid()), "OS_TEST_LABEL": label, "OS_TEST_SLEEP_S": TASK_SLEEP_S}
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
        plan_id = kernel.create_plan(contract(), draft).plan_id
        enqueue_pending(engine, client)
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
                reconcile(engine, client, kernel)
                enqueue_pending(engine, client)
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
