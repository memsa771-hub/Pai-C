"""Kernel side of the dual-write rule: send unsent enqueue requests to DBOS through a client only."""

from dbos import DBOSClient, EnqueueOptions
from sqlalchemy import Engine, select, update

from app.os import models
from app.os.runner.workflow import APP_VERSION, QUEUE_NAME, WORKFLOW_NAME, workflow_id

R = models.enqueue_requests


def enqueue(client: DBOSClient, task_id: int, attempt: int) -> None:
    # The workflow ID is the idempotency key: enqueueing it again returns the same workflow.
    options: EnqueueOptions = {
        "queue_name": QUEUE_NAME,
        "workflow_name": WORKFLOW_NAME,
        "workflow_id": workflow_id(task_id, attempt),
        "app_version": APP_VERSION,
    }
    client.enqueue(options, task_id, attempt)


def enqueue_pending(engine: Engine, client: DBOSClient, tenant_id: str) -> int:
    """Sends the tenant's unsent requests, then marks each sent. A crash in between only re-sends (harmless)."""
    with engine.connect() as conn:
        rows = conn.execute(select(R.c.id, R.c.task_id, R.c.attempt).where(
            R.c.sent.is_(False), R.c.tenant_id == tenant_id).order_by(R.c.id)).all()
    for row in rows:
        enqueue(client, row.task_id, row.attempt)
        with engine.begin() as conn:
            conn.execute(update(R).where(R.c.id == row.id).values(sent=True))
    return len(rows)
