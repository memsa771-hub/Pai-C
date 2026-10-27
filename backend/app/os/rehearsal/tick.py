"""The rehearsal tick: in rehearsal mode the worker has no cron schedules, so time-based work runs only when an admin
asks, through one `os.rehearsal_tick` workflow that runs the scheduled jobs once, in a fixed order (spec §2.2).

Each job is a DBOS step with the runner's step config, exactly as its scheduled form is (invariant 7: no other retry).
A job that still fails after its step retries ends the tick as `error`; the jobs after it do not run."""

import uuid
from collections.abc import Callable, Mapping

from dbos import DBOS, EnqueueOptions

from app.os.runner.workflow import (
    APP_VERSION,
    FAILED_WORKFLOW_STATUSES,
    QUEUE_NAME,
    STEP_CONFIG,
)

TICK_WORKFLOW = "os.rehearsal_tick"
# counsellor_intake is not here: the Counsellor module is off for the pilot (Slice 8 S8-D2), so it is never ticked.
JOB_ORDER = ("deadline_engine", "reminders", "replan", "deliver_outbox", "freshness", "documents_retry", "reconcile")


def run_tick(jobs: Mapping[str, Callable[[], object]]) -> list[str]:
    """Runs the jobs named in JOB_ORDER that are present, in that order. Returns the names run."""
    ran = []
    for name in JOB_ORDER:
        if name in jobs:
            jobs[name]()
            ran.append(name)
    return ran


def register_tick(jobs: Mapping[str, Callable[[], object]]) -> None:
    """Registers os.rehearsal_tick over the worker's job callables. Must run before DBOS.launch()."""
    steps = {name: DBOS.step(name=f"os.tick.{name}", **STEP_CONFIG)(fn) for name, fn in jobs.items()
             if name in JOB_ORDER}

    def rehearsal_tick() -> list[str]:
        return run_tick(steps)

    DBOS.workflow(name=TICK_WORKFLOW)(rehearsal_tick)


def enqueue_tick(client, tenant_id: str) -> str:
    """Puts one tick on the OS queue and returns its workflow ID (the tick ID)."""
    wid = f"{_prefix(tenant_id)}{uuid.uuid4().hex}"
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": TICK_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options)
    return wid


def _prefix(tenant_id: str) -> str:
    return f"rehearsal-tick:{tenant_id}:"


def tick_status(client, tenant_id: str, tick_id: str) -> dict | None:
    """`running`, `done` or `error`, and the jobs run (empty until done). None when this tenant has no such tick."""
    if not tick_id.startswith(_prefix(tenant_id)):
        return None
    found = client.list_workflows(workflow_ids=[tick_id], name=TICK_WORKFLOW, load_input=False)
    if not found:
        return None
    status = found[0].status
    if status == "SUCCESS":
        return {"status": "done", "ran": list(found[0].output or [])}
    if status in FAILED_WORKFLOW_STATUSES:
        return {"status": "error", "ran": []}
    return {"status": "running", "ran": []}
