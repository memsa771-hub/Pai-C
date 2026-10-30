"""The DBOS side of the runner: config, the `os.run_attempt` workflow and scheduled jobs.

Lessons from Spike 3 (handoff §6): a stable executor ID per worker replica, an explicit
application_version, and registration before DBOS.launch() into the current registry.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from dbos import DBOS, DBOSConfig
from sqlalchemy import Engine, select

from app.os import models
from app.os.kernel import Kernel, Outcome
from app.os.runner.registry import Registry, TaskContext
from app.os.settings import OsSettings

APP_NAME = "pai-os"
APP_VERSION = "os-1"
QUEUE_NAME = "os"
WORKFLOW_NAME = "os.run_attempt"
STEP_CONFIG = {"retries_allowed": True, "max_attempts": 3}  # invariant 7: the only retry mechanism
FAILED_WORKFLOW_STATUSES = frozenset({"ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"})
DEFAULT_WORKER_CONCURRENCY = 4


def workflow_id(task_id: int, attempt: int) -> str:
    return f"{task_id}:{attempt}"


def dbos_config(settings: OsSettings, executor_id: str | None) -> DBOSConfig:
    if not executor_id or executor_id == "local":
        raise ValueError("a stable, unique executor ID per worker is required (not empty, not 'local')")
    return {
        "name": APP_NAME,
        "system_database_url": settings.database_url,
        "dbos_system_schema": settings.dbos_system_schema,
        "application_version": APP_VERSION,
        "executor_id": executor_id,
    }


@dataclass
class _Jobs:
    schedules: list[dict]


_jobs = _Jobs(schedules=[])


def register_workflow(engine: Engine, settings: OsSettings, registry: Registry, kernel: Kernel) -> None:
    """Registers os.run_attempt and its steps. Must run before DBOS.launch()."""
    T = models.tasks

    def load(task_id: int, attempt: int) -> dict | None:
        with engine.connect() as conn:
            row = conn.execute(select(T).where(T.c.id == task_id, T.c.tenant_id == kernel.tenant_id)).first()
        if row is None or row.attempt != attempt or not kernel.mark_running(task_id, attempt):
            return None  # another tenant's task, superseded, or already settled: nothing to run
        return asdict(TaskContext(task_id=task_id, attempt=attempt, task_type=row.task_type, plan_id=row.plan_id,
                                  programme_ref=row.programme_ref, payload=row.result or {},
                                  fact_refs=list(row.fact_refs or [])))

    def handle(ctx: dict) -> dict:
        module = registry.owner(ctx["task_type"])
        if module.handler is None:
            raise RuntimeError(f"task type {ctx['task_type']} is student-owned and cannot be executed")
        return asdict(module.handler(TaskContext(**ctx)))

    def apply(task_id: int, attempt: int, outcome: dict) -> None:
        kernel.apply_result(task_id, attempt, Outcome(**outcome))

    load_step = DBOS.step(name="os.load", **STEP_CONFIG)(load)
    handle_step = DBOS.step(name="os.handle", **STEP_CONFIG)(handle)
    apply_step = DBOS.step(name="os.apply", **STEP_CONFIG)(apply)

    def run_attempt(task_id: int, attempt: int) -> None:
        ctx = load_step(task_id, attempt)
        if ctx is None:
            return
        apply_step(task_id, attempt, handle_step(ctx))

    DBOS.workflow(name=WORKFLOW_NAME)(run_attempt)
    _jobs.schedules = []


def register_job(name: str, cron: str, fn: Callable[[], Any]) -> None:
    """A scheduled job (DBOS schedule: one run per tick across replicas). Register before launch()."""
    step = DBOS.step(name=f"os.job.{name}", **STEP_CONFIG)(fn)

    def job(scheduled_time, context) -> None:
        step()

    wf = DBOS.workflow(name=f"os.job.{name}")(job)
    _jobs.schedules.append({"schedule_name": f"os.{name}", "workflow_fn": wf, "schedule": cron})


def launch(worker_concurrency: int = DEFAULT_WORKER_CONCURRENCY) -> None:
    DBOS.launch()
    DBOS.register_queue(QUEUE_NAME, worker_concurrency=worker_concurrency)
    if _jobs.schedules:
        DBOS.apply_schedules(_jobs.schedules)
