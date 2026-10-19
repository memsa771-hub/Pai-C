"""Test-only runner modules. Loaded into worker subprocesses through OS_EXTRA_MODULES."""

import os
import time
from functools import cache

from sqlalchemy import create_engine, text

from app.os.kernel import Outcome
from app.os.runner import Module, TaskContext

RUNS_DDL = """
CREATE TABLE IF NOT EXISTS public.os_test_runs (
    id bigserial PRIMARY KEY, task_id bigint NOT NULL, attempt int NOT NULL, label text NOT NULL,
    at timestamptz NOT NULL DEFAULT clock_timestamp())
"""


@cache
def _engine():
    # Worker subprocesses get OS_DATABASE_URL; in-process tests (and CI) only set OS_TEST_DATABASE_URL.
    url = os.environ.get("OS_DATABASE_URL") or os.environ["OS_TEST_DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


def _sleep(ctx: TaskContext) -> Outcome:
    # One row per execution (append-only), so re-runs after a kill are visible.
    with _engine().begin() as conn:
        conn.execute(text(RUNS_DDL))
        conn.execute(text("INSERT INTO public.os_test_runs (task_id, attempt, label) VALUES (:t, :a, :l)"),
                     {"t": ctx.task_id, "a": ctx.attempt, "l": os.environ.get("OS_TEST_LABEL", "inproc")})
    time.sleep(float(os.environ.get("OS_TEST_SLEEP_S", "1.5")))
    return Outcome("done", {"slept": True})


def _fail(ctx: TaskContext) -> Outcome:
    raise RuntimeError("test module always fails")


SLEEP_MODULE = Module(name="test.sleep", owns=frozenset({"test.sleep"}), handler=_sleep)
FAIL_MODULE = Module(name="test.fail", owns=frozenset({"test.fail"}), handler=_fail)
