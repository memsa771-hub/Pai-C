"""Reconciler: repairs any mismatch between kernel state and DBOS, in either direction (spec §4.6)."""

from dbos import DBOSClient
from sqlalchemy import Engine, select, update

from app.os import models
from app.os.kernel import Kernel, Outcome
from app.os.runner.enqueue import enqueue
from app.os.runner.workflow import FAILED_WORKFLOW_STATUSES, workflow_id

T = models.tasks


def reconcile(engine: Engine, client: DBOSClient, kernel: Kernel) -> dict[str, int]:
    """- an open work task whose workflow DBOS never saw: enqueue it again (same workflow ID);
    - an open task whose workflow ended ERROR / CANCELLED / MAX_RECOVERY_ATTEMPTS_EXCEEDED: fail it
      with reason `workflow_error` (otherwise it would be silently lost).
    """
    counts = {"reenqueued": 0, "present": 0, "failed_workflows": 0}
    with engine.connect() as conn:
        open_tasks = conn.execute(select(T.c.id, T.c.attempt, T.c.state).where(
            T.c.tenant_id == kernel.tenant_id, T.c.kind == "work", T.c.state.in_(("ready", "running")),
            T.c.attempt > 0,
        ).order_by(T.c.id)).all()
    for task in open_tasks:
        wid = workflow_id(task.id, task.attempt)
        found = client.list_workflows(workflow_ids=[wid], load_input=False, load_output=False)
        if not found:
            enqueue(client, task.id, task.attempt)
            with engine.begin() as conn:
                conn.execute(update(models.enqueue_requests).where(
                    models.enqueue_requests.c.task_id == task.id, models.enqueue_requests.c.attempt == task.attempt,
                ).values(sent=True))
            counts["reenqueued"] += 1
            continue
        counts["present"] += 1
        if found[0].status in FAILED_WORKFLOW_STATUSES:
            kernel.apply_result(task.id, task.attempt, Outcome("failed", reason="workflow_error"))
            counts["failed_workflows"] += 1
    return counts
