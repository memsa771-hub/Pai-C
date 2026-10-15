"""Spike 3: the core loop runs each task attempt exactly once.

Kernel marks a task ready -> enqueuer -> DBOS queue -> workflow (load page, AI extract,
record result, complete). Real Postgres, TestModel instead of a paid model.
"""

import threading
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from dbos import DBOS
from psycopg.types.json import Jsonb
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from spikes.spike3 import loop
from spikes.spike3.loop import enqueue_pending, mark_ready, reconcile

VALID_QUOTE = "Language requirements: English at level"
OUTPUT = {"field": "language_requirement", "value": "English certificate required", "quote": VALID_QUOTE}
BAD_QUOTE_OUTPUT = {"field": "deadline", "value": "15 July", "quote": "text that is not on the page"}
TIMEOUT_S = 30.0
SPIKE3_TABLES = ("tasks", "model_calls", "enqueue_requests", "results", "step_runs")


# --- fixtures -------------------------------------------------------------------------


@pytest.fixture
def conn(pg_url: str, fresh_db: None) -> Iterator[psycopg.Connection]:
    with psycopg.connect(pg_url, autocommit=True) as connection:
        loop.apply_schema(connection)
        tables = ", ".join(f"spike3.{name}" for name in SPIKE3_TABLES)
        connection.execute(f"TRUNCATE {tables} RESTART IDENTITY")
        yield connection


def _wait_no_open_workflows(timeout_s: float = TIMEOUT_S) -> None:
    """Lets the test's workflows finish (a task is settled before its workflow returns)."""
    deadline = time.monotonic() + timeout_s
    while True:
        open_ids = [
            wf.workflow_id
            for wf in DBOS.list_workflows(status=["PENDING", "ENQUEUED"], load_input=False, load_output=False)
        ]
        if not open_ids:
            return
        if time.monotonic() > deadline:
            pytest.fail(f"workflows still open after {timeout_s:.0f}s: {open_ids}")
        time.sleep(0.1)


def _run_dbos(pg_url: str, model: Model) -> Iterator[None]:
    try:
        loop.start(database_url=pg_url, system_database_url=pg_url, schema="dbos_test", model=model)
        yield
        _wait_no_open_workflows()
    finally:
        loop.shutdown()


@pytest.fixture
def dbos_runtime(pg_url: str, conn: psycopg.Connection) -> Iterator[None]:
    # The valid quote must be on whichever page a task loads.
    for path in loop.page_paths():
        assert VALID_QUOTE in path.read_text(encoding="utf-8"), path.name
    yield from _run_dbos(pg_url, TestModel(custom_output_args=OUTPUT))


@pytest.fixture
def dbos_runtime_bad_quote(pg_url: str, conn: psycopg.Connection) -> Iterator[None]:
    yield from _run_dbos(pg_url, TestModel(custom_output_args=BAD_QUOTE_OUTPUT))


def _always_fails(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    raise RuntimeError("model service unavailable")


@pytest.fixture
def dbos_runtime_model_down(pg_url: str, conn: psycopg.Connection) -> Iterator[None]:
    yield from _run_dbos(pg_url, FunctionModel(_always_fails, model_name="always-fails"))


# --- helpers --------------------------------------------------------------------------


def _scalar(conn: psycopg.Connection, sql: str, params: tuple) -> object:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def task_status(conn: psycopg.Connection, task_id: str) -> str | None:
    return _scalar(conn, "SELECT status FROM spike3.tasks WHERE id = %s", (task_id,))


def failure_reason(conn: psycopg.Connection, task_id: str) -> str | None:
    return _scalar(conn, "SELECT failure_reason FROM spike3.tasks WHERE id = %s", (task_id,))


def result_count(conn: psycopg.Connection, task_id: str) -> int:
    return _scalar(conn, "SELECT count(*) FROM spike3.results WHERE task_id = %s", (task_id,))


def model_calls(conn: psycopg.Connection, task_id: str) -> int:
    return _scalar(conn, "SELECT count(*) FROM spike3.model_calls WHERE task_id = %s", (task_id,))


def step_run_count(conn: psycopg.Connection, task_id: str, step: str) -> int:
    return _scalar(
        conn, "SELECT count(*) FROM spike3.step_runs WHERE task_id = %s AND step = %s", (task_id, step)
    )


def workflow_count(workflow_id: str) -> int:
    return len(DBOS.list_workflows(workflow_ids=[workflow_id], load_input=False, load_output=False))


def wait_workflow_status(workflow_id: str, status: str) -> None:
    deadline = time.monotonic() + TIMEOUT_S
    while (wf := DBOS.get_workflow_status(workflow_id)) is None or wf.status != status:
        if time.monotonic() > deadline:
            pytest.fail(f"workflow {workflow_id!r} is {wf and wf.status!r}, not {status!r}")
        time.sleep(0.1)


class StatusClient:
    """Stands in for a DBOSClient: every workflow it is asked about has `status`."""

    def __init__(self, status: str) -> None:
        self.status = status

    def list_workflows(self, *, workflow_ids: list[str], **_: Any) -> list[SimpleNamespace]:
        return [SimpleNamespace(workflow_id=wid, status=self.status) for wid in workflow_ids]


def unmark_sent(conn: psycopg.Connection, task_id: str) -> None:
    conn.execute("UPDATE spike3.enqueue_requests SET sent = false WHERE task_id = %s", (task_id,))


def record_result_sql(conn: psycopg.Connection, task_id: str, attempt: int, output: dict[str, str]) -> None:
    """Runs the exact statement the record_result step uses."""
    conn.execute(loop.RECORD_RESULT_SQL, (task_id, attempt, Jsonb(output), True))


def _wait_settled(conn: psycopg.Connection, task_id: str, timeout_s: float = TIMEOUT_S) -> str:
    deadline = time.monotonic() + timeout_s
    while True:
        status = task_status(conn, task_id)
        if status in ("done", "failed"):
            return status
        if time.monotonic() > deadline:
            pytest.fail(f"task {task_id!r} still {status!r} after {timeout_s:.0f}s")
        time.sleep(0.1)


def wait_settled(conn: psycopg.Connection, task_id: str) -> None:
    _wait_settled(conn, task_id)


def wait_done(conn: psycopg.Connection, task_id: str) -> None:
    status = _wait_settled(conn, task_id)
    assert status == "done", f"task {task_id!r} settled as {status!r} ({failure_reason(conn, task_id)!r})"


def run_concurrently(*fns: Callable[[], Any]) -> list[Any]:
    """Starts every function at the same moment on its own thread.

    Returns their results in argument order; re-raises the first error.
    """
    barrier = threading.Barrier(len(fns))
    errors: list[BaseException] = []
    results: list[Any] = [None] * len(fns)

    def runner(index: int, fn: Callable[[], Any]) -> None:
        barrier.wait()
        try:
            results[index] = fn()
        except BaseException as exc:  # re-raised on the test thread below
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(fns)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT_S)
        assert not thread.is_alive(), "concurrent call did not finish"
    if errors:
        raise errors[0]
    return results


# --- tests ----------------------------------------------------------------------------


def test_happy_path(dbos_runtime, conn):
    mark_ready(conn, "t1"); enqueue_pending(conn); wait_done(conn, "t1")
    assert result_count(conn, "t1") == 1 and task_status(conn, "t1") == "done"

def test_record_result_is_idempotent(conn):
    record_result_sql(conn, "t1", 1, OUTPUT); record_result_sql(conn, "t1", 1, OUTPUT)
    assert result_count(conn, "t1") == 1

def test_enqueue_twice_runs_once(dbos_runtime, conn):
    mark_ready(conn, "t2"); enqueue_pending(conn)
    unmark_sent(conn, "t2")              # simulate crash before marking sent
    enqueue_pending(conn); wait_done(conn, "t2")
    assert workflow_count("t2:1") == 1 and result_count(conn, "t2") == 1
    assert model_calls(conn, "t2") == 1
    assert step_run_count(conn, "t2", "load_page") == 1

def test_reconciler_and_enqueuer_race(dbos_runtime, conn):
    mark_ready(conn, "t3")
    enqueued, reconciled = run_concurrently(lambda: enqueue_pending(conn), lambda: reconcile(conn))
    wait_done(conn, "t3")
    assert workflow_count("t3:1") == 1 and result_count(conn, "t3") == 1
    assert model_calls(conn, "t3") == 1
    assert step_run_count(conn, "t3", "load_page") == 1
    # enqueue_pending returns 0 only if reconcile enqueued t3:1 and marked it sent before
    # enqueue_pending's first SELECT, so which side enqueues is timing; that one did is not.
    assert enqueued == 1 or reconciled["reenqueued"] == 1
    # reconcile reads the task while it is still open (its workflow cannot finish before the
    # queue picks it up), so it either enqueued t3:1 itself or found DBOS already had it.
    assert reconciled["reenqueued"] + reconciled["present"] == 1

def test_invalid_quote_is_retried_then_fails(dbos_runtime_bad_quote, conn):
    # fixture builds the agent with TestModel(custom_output_args={"field": "deadline",
    #   "value": "15 July", "quote": "text that is not on the page"})
    mark_ready(conn, "t4"); enqueue_pending(conn); wait_settled(conn, "t4")
    assert task_status(conn, "t4") == "failed"
    assert failure_reason(conn, "t4") == "invalid_output"
    assert model_calls(conn, "t4") == 3   # first try + 2 output retries

@pytest.mark.parametrize("status", ["ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"])
def test_reconcile_fails_task_whose_workflow_ended_without_success(conn, status):
    mark_ready(conn, "t5")
    counts = reconcile(conn, client=StatusClient(status))
    assert counts["failed_workflows"] == 1 and counts["present"] == 1
    assert task_status(conn, "t5") == "failed"
    assert failure_reason(conn, "t5") == "workflow_error"
    assert reconcile(conn, client=StatusClient(status))["failed_workflows"] == 0   # task no longer open

def test_reconcile_fails_task_of_errored_workflow(dbos_runtime_model_down, conn):
    mark_ready(conn, "t6"); enqueue_pending(conn)
    wait_workflow_status("t6:1", "ERROR")   # model step retried, then the workflow raised
    assert task_status(conn, "t6") == "running"
    assert model_calls(conn, "t6") == 3     # invariant 7: DBOS step retries (max_attempts=3)
    assert reconcile(conn)["failed_workflows"] == 1
    assert task_status(conn, "t6") == "failed" and failure_reason(conn, "t6") == "workflow_error"
