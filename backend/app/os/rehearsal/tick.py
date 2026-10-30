"""The rehearsal tick: in rehearsal mode the worker has no cron schedules, so time-based work runs only when an admin
asks, through one `os.rehearsal_tick` workflow that runs the scheduled jobs once, in a fixed order (spec §2.2).

Each job is a DBOS step with the runner's step config, exactly as its scheduled form is (invariant 7: no other retry).
A job that still fails after its step retries is logged and listed in `failed`, and the tick goes on with the next job,
as independent cron runs would: one broken job must not stall a rehearsal that ticks again and again."""

import logging
import uuid
from collections.abc import Callable, Mapping

from dbos import DBOS, EnqueueOptions

from app.os.runner.workflow import (
    APP_VERSION,
    FAILED_WORKFLOW_STATUSES,
    QUEUE_NAME,
    STEP_CONFIG,
)

log = logging.getLogger("app.os.rehearsal")

TICK_WORKFLOW = "os.rehearsal_tick"
# counsellor_intake is not here: the Counsellor module is off for the pilot (Slice 8 S8-D2), so it is never ticked.
JOB_ORDER = ("deadline_engine", "reminders", "replan", "deliver_outbox", "freshness", "documents_retry", "reconcile")


def run_tick(jobs: Mapping[str, Callable[[], object]]) -> dict[str, list[str]]:
    """Runs every job named in JOB_ORDER that is present, in that order, even after one fails. Returns
    `{"ran": names that completed, "failed": names that raised}`. Catching here records the failure; it is not a
    retry (the step's own retries are already spent)."""
    ran: list[str] = []
    failed: list[str] = []
    for name in JOB_ORDER:
        if name not in jobs:
            continue
        try:
            jobs[name]()
        except Exception:  # noqa: BLE001  (recorded and reported by the tick; the next job still runs)
            log.exception("rehearsal tick: job %s failed", name)
            failed.append(name)
        else:
            ran.append(name)
    return {"ran": ran, "failed": failed}


def register_tick(jobs: Mapping[str, Callable[[], object]]) -> None:
    """Registers os.rehearsal_tick over the worker's job callables. Must run before DBOS.launch()."""
    steps = {name: DBOS.step(name=f"os.tick.{name}", **STEP_CONFIG)(fn) for name, fn in jobs.items()
             if name in JOB_ORDER}

    def rehearsal_tick() -> dict[str, list[str]]:
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
    """`running`, `done` (every job completed) or `error` (a job failed, or the workflow itself did), with the jobs
    that completed and those that failed (both empty until it ends). None when this tenant has no such tick."""
    if not tick_id.startswith(_prefix(tenant_id)):
        return None
    found = client.list_workflows(workflow_ids=[tick_id], name=TICK_WORKFLOW, load_input=False)
    if not found:
        return None
    status, output = found[0].status, found[0].output or {}
    if status == "SUCCESS":
        ran, failed = list(output.get("ran", [])), list(output.get("failed", []))
        return {"status": "error" if failed else "done", "ran": ran, "failed": failed}
    if status in FAILED_WORKFLOW_STATUSES:
        return {"status": "error", "ran": [], "failed": []}
    return {"status": "running", "ran": [], "failed": []}
