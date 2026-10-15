"""Spike 3 (throwaway): the chaos run. Workers die at random; no task may be lost or duplicated.

    python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model openai --timeout 1800

The driver is the kernel side and never executes workflows: it reaches DBOS only through a
`DBOSClient`. It resets the spike tables and its own DBOS system schema (default `dbos_chaos`),
starts `workers` worker subprocesses (`spikes.spike3.worker`), marks `tasks` tasks ready and
enqueues them. Until every task has settled (or `timeout_s` passes) it:

- every `kill_every_s`: SIGKILLs the worker in a random slot and starts its replacement in the
  same slot (same executor ID `spike3-w{slot}`, so DBOS recovers the dead worker's workflows;
  new process label `w{slot}g{generation}`);
- every `reconcile_every_s` (5 s for the spike, 5 minutes in production): runs `loop.reconcile`.

Then it stops the workers and measures the run from the spike tables and DBOS (`ChaosReport`).

Reads OS_DATABASE_URL (or DATABASE_URL); `--model openai` also needs OS_OPENAI_API_KEY.
Destructive: it empties the `spike3` schema and drops the chosen DBOS schema of that database.
"""

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Literal

import psycopg
from dbos import DBOSClient, WorkflowStatus
from psycopg import sql

from app.os.settings import load_settings
from spikes.spike3 import loop
from spikes.spike3.worker import DEFAULT_MODEL_DELAY_S, DEFAULT_WORKER_CONCURRENCY

BACKEND_DIR = loop.SPIKE_DIR.parents[1]
DEFAULT_SCHEMA = "dbos_chaos"
SPIKE3_TABLES = ("tasks", "model_calls", "enqueue_requests", "results", "step_runs")
STARTUP_TIMEOUT_S = 60.0
DRAIN_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 15.0
PASS_BAR_VALID_RATE = 0.99

# --- measurement SQL ------------------------------------------------------------------

TASK_COUNTS_SQL = """
SELECT count(*) FILTER (WHERE status = 'done'),
       count(*) FILTER (WHERE status = 'failed'),
       count(*) FILTER (WHERE status IN ('ready', 'running'))
FROM spike3.tasks
"""
RESULT_COUNTS_SQL = """
SELECT count(*) - count(DISTINCT (task_id, attempt)), count(*) FILTER (WHERE valid)
FROM spike3.results
"""
STEP_RERUNS_SQL = """
SELECT coalesce(sum(n - 1), 0)
FROM (SELECT count(*) AS n FROM spike3.step_runs GROUP BY task_id, attempt, step) AS runs
"""
# Kills as (worker label, database time once the process was gone); params: labels, times.
KILLS_CTE = "WITH kills AS (SELECT * FROM unnest(%s::text[], %s::timestamptz[]) AS k(worker, killed_at))"
# A step run that was run again must have been cut short by a kill of its worker, and that kill
# must come before the re-run started. Anything else is a duplicate.
DUPLICATED_STEPS_SQL = KILLS_CTE + """
SELECT count(*) FROM (
    SELECT worker, lead(at) OVER (PARTITION BY task_id, attempt, step ORDER BY id) AS next_at
    FROM spike3.step_runs
) AS runs LEFT JOIN kills USING (worker)
WHERE runs.next_at IS NOT NULL AND (kills.killed_at IS NULL OR kills.killed_at > runs.next_at)
"""
# Model requests repeat inside one process (output retries, step retries); a request followed
# by one from another process means the attempt moved, which only an earlier kill may cause.
DUPLICATED_MODEL_CALLS_SQL = KILLS_CTE + """
SELECT count(*) FROM (
    SELECT worker,
           lead(worker) OVER (PARTITION BY task_id, attempt ORDER BY id) AS next_worker,
           lead(at) OVER (PARTITION BY task_id, attempt ORDER BY id) AS next_at
    FROM spike3.model_calls
) AS calls LEFT JOIN kills USING (worker)
WHERE calls.next_worker IS NOT NULL AND calls.next_worker IS DISTINCT FROM calls.worker
  AND (kills.killed_at IS NULL OR kills.killed_at > calls.next_at)
"""
NOW_SQL = "SELECT clock_timestamp()"
# Attempts whose rows were written by more than one worker process: interrupted, then recovered.
RECOVERED_ATTEMPTS_SQL = """
SELECT count(*) FROM (
    SELECT task_id, attempt FROM (
        SELECT task_id, attempt, worker FROM spike3.step_runs
        UNION ALL
        SELECT task_id, attempt, worker FROM spike3.model_calls
    ) AS rows
    GROUP BY task_id, attempt
    HAVING count(DISTINCT worker) > 1
) AS moved
"""
MULTI_ATTEMPT_TASKS_SQL = "SELECT id FROM spike3.tasks WHERE attempt <> 1"
MODEL_CALLS_SQL = "SELECT count(*) FROM spike3.model_calls"


@dataclass(frozen=True)
class ChaosReport:
    tasks: int
    done: int
    failed: int
    lost: int  # tasks - done - failed
    duplicate_results: int  # results rows beyond one per task attempt (0 by the primary key)
    duplicated: int  # re-runs not caused by a kill (step re-runs, cross-process model requests)
    extra_workflows: int  # tasks with more than one attempt or more than one workflow ID
    step_reruns: int  # step_runs rows beyond one per (task, attempt, step)
    recovered_attempts: int  # attempts whose rows come from more than one worker process
    valid_outputs: int
    model_calls: int
    valid_rate: float  # valid_outputs / tasks
    kills: int
    kills_in_flight: int  # kills of a worker that had PENDING workflows at that moment
    interrupted_workflows: int  # PENDING workflows of killed workers, summed over kills
    unexpected_exits: int  # workers that exited without being killed (restarted in place)
    failed_workflows: int  # tasks failed by reconcile because their workflow ended without success
    reconcile_reenqueued: int
    reconcile_applied: int
    workflows: int  # run_attempt workflows DBOS knows
    open_workflows: int  # still PENDING/ENQUEUED when the workers were stopped
    timed_out: bool
    elapsed_s: float
    model: str
    workers: int
    kill_every_s: float
    log_dir: str = field(default="")


def pass_bar_failures(report: ChaosReport) -> list[str]:
    """Spike 3 pass bar: zero lost, zero duplicated; at least 99% valid structured outputs."""
    checks = {
        "lost == 0": report.lost == 0,
        "duplicated == 0": report.duplicated == 0,
        "duplicate_results == 0": report.duplicate_results == 0,
        "extra_workflows == 0": report.extra_workflows == 0,
        f"valid_rate >= {PASS_BAR_VALID_RATE}": report.valid_rate >= PASS_BAR_VALID_RATE,
        "not timed_out": not report.timed_out,
    }
    return [name for name, ok in checks.items() if not ok]


def executor_id(slot: int) -> str:
    return f"spike3-w{slot}"


def task_id(index: int) -> str:
    return f"chaos-{index:04d}"


# --- worker processes -----------------------------------------------------------------


@dataclass
class _Worker:
    slot: int
    generation: int
    proc: "subprocess.Popen[bytes]"
    log: IO[bytes]

    @property
    def label(self) -> str:
        return f"w{self.slot}g{self.generation}"


class _Workers:
    """One worker subprocess per slot. Every exit path must end in stop() (no orphans)."""

    def __init__(self, *, worker_args: list[str], env: dict[str, str], log_dir: Path) -> None:
        self.worker_args = worker_args
        self.env = env
        self.log_dir = log_dir
        self.slots: dict[int, _Worker] = {}
        self.generations: Counter[int] = Counter()

    def start(self, slot: int) -> _Worker:
        generation = self.generations[slot]
        self.generations[slot] += 1
        label = f"w{slot}g{generation}"
        log = open(self.log_dir / f"{label}.log", "wb")
        proc = subprocess.Popen(
            [sys.executable, "-m", "spikes.spike3.worker", *self.worker_args, "--executor-id", executor_id(slot)],
            cwd=BACKEND_DIR,
            env={**self.env, "SPIKE3_WORKER": label},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        worker = self.slots[slot] = _Worker(slot, generation, proc, log)
        return worker

    def kill(self, slot: int) -> str:
        """SIGKILLs the slot's worker and waits until it is gone. The caller starts the replacement
        (only then: two live processes must never share an executor ID)."""
        worker = self.slots[slot]
        worker.proc.send_signal(signal.SIGKILL)
        worker.proc.wait()
        worker.log.close()
        return worker.label

    def restart_exited(self) -> list[str]:
        """Restarts workers that exited on their own; returns their labels."""
        exited = []
        for slot, worker in list(self.slots.items()):
            if worker.proc.poll() is not None:
                worker.log.close()
                exited.append(worker.label)
                self.start(slot)
        return exited

    def stop(self) -> None:
        workers = list(self.slots.values())
        for worker in workers:
            if worker.proc.poll() is None:
                worker.proc.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + STOP_TIMEOUT_S
        for worker in workers:
            try:
                worker.proc.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                worker.proc.kill()
                worker.proc.wait()
            worker.log.close()
        self.slots.clear()


# --- driver ---------------------------------------------------------------------------


def _reset(conn: psycopg.Connection, schema: str) -> None:
    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    loop.apply_schema(conn)
    conn.execute(f"TRUNCATE {', '.join(f'spike3.{name}' for name in SPIKE3_TABLES)} RESTART IDENTITY")


def _wait_ready(client: DBOSClient, workers: _Workers) -> None:
    """Waits until a worker has migrated the DBOS schema and registered the queue."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while True:
        try:
            if client.retrieve_queue(loop.QUEUE_NAME) is not None:
                return
        except Exception:  # the DBOS system tables do not exist yet
            pass
        for worker in workers.slots.values():
            if worker.proc.poll() is not None:
                raise RuntimeError(f"worker {worker.label} exited during startup; see {worker.log.name}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"no worker registered queue {loop.QUEUE_NAME!r} in {STARTUP_TIMEOUT_S:.0f}s")
        time.sleep(0.2)


def _list_workflows(client: DBOSClient, **filters: Any) -> list[WorkflowStatus]:
    return client.list_workflows(name=loop.WORKFLOW_NAME, load_input=False, load_output=False, **filters)


def _open_tasks(conn: psycopg.Connection) -> int:
    return len(conn.execute(loop.OPEN_TASKS_SQL).fetchall())


def _wait_drained(client: DBOSClient, timeout_s: float) -> int:
    """Lets the last workflows record SUCCESS (their task settles in their last step)."""
    deadline = time.monotonic() + timeout_s
    while True:
        still_open = len(_list_workflows(client, status=["PENDING", "ENQUEUED"]))
        if still_open == 0 or time.monotonic() > deadline:
            return still_open
        time.sleep(0.2)


def _db_now(conn: psycopg.Connection) -> datetime:
    row = conn.execute(NOW_SQL).fetchone()
    assert row is not None
    return row[0]


def _scalar(conn: psycopg.Connection, query: str, params: tuple = ()) -> int:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return int(row[0])


def run_chaos(
    tasks: int,
    workers: int,
    kill_every_s: float,
    model: Literal["test", "openai"],
    timeout_s: int,
    *,
    database_url: str | None = None,
    schema: str = DEFAULT_SCHEMA,
    model_delay_s: float = DEFAULT_MODEL_DELAY_S,
    worker_concurrency: int = DEFAULT_WORKER_CONCURRENCY,
    reconcile_every_s: float = 5.0,
    seed: int | None = None,
    log_dir: Path | None = None,
) -> ChaosReport:
    if model == "openai" and not os.environ.get("OS_OPENAI_API_KEY"):
        raise ValueError("model 'openai' needs OS_OPENAI_API_KEY (the dev key); it is not set")
    if not schema.startswith(DEFAULT_SCHEMA):
        raise ValueError(f"schema must start with {DEFAULT_SCHEMA!r}: the run drops it")
    database_url = database_url or load_settings().database_url
    log_dir = log_dir or Path(tempfile.mkdtemp(prefix="spike3-chaos-"))
    log_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    started = time.monotonic()
    deadline = started + timeout_s

    pool = _Workers(
        worker_args=["--model", model, "--model-delay", str(model_delay_s),
                     "--worker-concurrency", str(worker_concurrency)],
        env={**os.environ, "OS_DATABASE_URL": database_url, "OS_DBOS_SYSTEM_SCHEMA": schema,
             "SPIKE3_DRIVER_PID": str(os.getpid()), "PYTHONUNBUFFERED": "1"},
        log_dir=log_dir,
    )
    killed: list[str] = []
    killed_at: list[datetime] = []
    kills_in_flight = interrupted = unexpected_exits = 0
    reconciled: Counter[str] = Counter()
    timed_out = False
    open_workflows = 0

    with psycopg.connect(database_url, autocommit=True) as conn:
        _reset(conn, schema)
        client: DBOSClient | None = None
        try:
            try:
                for slot in range(workers):
                    pool.start(slot)
                client = DBOSClient(
                    system_database_url=database_url, dbos_system_schema=schema, application_name=loop.APP_NAME
                )
                _wait_ready(client, pool)
                for index in range(tasks):
                    loop.mark_ready(conn, task_id(index))
                loop.enqueue_pending(conn, client=client)

                next_kill = time.monotonic() + kill_every_s
                next_reconcile = time.monotonic() + reconcile_every_s
                while _open_tasks(conn) > 0:
                    now = time.monotonic()
                    if now > deadline:
                        timed_out = True
                        break
                    unexpected_exits += len(pool.restart_exited())
                    if now >= next_kill:
                        slot = rng.randrange(workers)
                        pending = len(_list_workflows(client, status="PENDING", executor_id=executor_id(slot)))
                        kills_in_flight += pending > 0
                        interrupted += pending
                        killed.append(pool.kill(slot))
                        killed_at.append(_db_now(conn))
                        pool.start(slot)
                        next_kill = time.monotonic() + kill_every_s
                    if now >= next_reconcile:
                        reconciled.update(loop.reconcile(conn, client=client))
                        next_reconcile = time.monotonic() + reconcile_every_s
                    time.sleep(0.1)
                open_workflows = _wait_drained(client, 0 if timed_out else DRAIN_TIMEOUT_S)
            finally:
                pool.stop()

            done, failed, _ = conn.execute(TASK_COUNTS_SQL).fetchone() or (0, 0, 0)
            duplicate_results, valid_outputs = conn.execute(RESULT_COUNTS_SQL).fetchone() or (0, 0)
            assert client is not None
            wf_tasks = Counter(wf.workflow_id.rsplit(":", 1)[0] for wf in _list_workflows(client))
            extra = {t for t, n in wf_tasks.items() if n > 1}
            extra |= {row[0] for row in conn.execute(MULTI_ATTEMPT_TASKS_SQL).fetchall()}
            return ChaosReport(
                tasks=tasks,
                done=done,
                failed=failed,
                lost=tasks - done - failed,
                duplicate_results=duplicate_results,
                duplicated=_scalar(conn, DUPLICATED_STEPS_SQL, (killed, killed_at))
                + _scalar(conn, DUPLICATED_MODEL_CALLS_SQL, (killed, killed_at)),
                extra_workflows=len(extra),
                step_reruns=_scalar(conn, STEP_RERUNS_SQL),
                recovered_attempts=_scalar(conn, RECOVERED_ATTEMPTS_SQL),
                valid_outputs=valid_outputs,
                model_calls=_scalar(conn, MODEL_CALLS_SQL),
                valid_rate=valid_outputs / tasks if tasks else 0.0,
                kills=len(killed),
                kills_in_flight=kills_in_flight,
                interrupted_workflows=interrupted,
                unexpected_exits=unexpected_exits,
                failed_workflows=reconciled["failed_workflows"],
                reconcile_reenqueued=reconciled["reenqueued"],
                reconcile_applied=reconciled["applied"],
                workflows=sum(wf_tasks.values()),
                open_workflows=open_workflows,
                timed_out=timed_out,
                elapsed_s=round(time.monotonic() - started, 1),
                model=model,
                workers=workers,
                kill_every_s=kill_every_s,
                log_dir=str(log_dir),
            )
        finally:
            if client is not None:
                client.destroy()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--kill-every", type=float, required=True, help="seconds between kills")
    parser.add_argument("--model", choices=["test", "openai"], required=True)
    parser.add_argument("--timeout", type=int, required=True, help="seconds")
    parser.add_argument("--model-delay", type=float, default=DEFAULT_MODEL_DELAY_S, help="test model only (s)")
    parser.add_argument("--worker-concurrency", type=int, default=DEFAULT_WORKER_CONCURRENCY)
    parser.add_argument("--schema", default=DEFAULT_SCHEMA, help="DBOS system schema (dropped first)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        report = run_chaos(
            args.tasks, args.workers, args.kill_every, args.model, args.timeout,
            schema=args.schema, model_delay_s=args.model_delay,
            worker_concurrency=args.worker_concurrency, seed=args.seed,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(report), indent=2))
    failures = pass_bar_failures(report)
    print("pass bar: " + ("PASS" if not failures else "FAIL (" + ", ".join(failures) + ")"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
