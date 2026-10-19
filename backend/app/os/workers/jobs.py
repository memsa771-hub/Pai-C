"""Scheduled jobs the worker registers: hourly deadline engine and reminders, outbox delivery every minute."""

from datetime import datetime, timezone

from app.os.knowledge import SqlKnowledge
from app.os.outbox import Outbox, make_sender
from app.os.playbooks import load_playbook_dir
from app.os.service import PlanService
from app.os.workers import deadline_engine
from app.os.workers.reminders import run_reminders


def _service(settings, engine, kernel) -> PlanService:
    return PlanService(engine, settings, kernel, SqlKnowledge(engine, settings.tenant_id), load_playbook_dir(),
                       today=lambda: datetime.now(timezone.utc).date())


def _deadlines(settings, engine, kernel, client):
    svc = _service(settings, engine, kernel)
    return lambda: deadline_engine.run(svc, engine)


def _reminders(settings, engine, kernel, client):
    box = Outbox(engine, settings.tenant_id)
    return lambda: run_reminders(engine, box, datetime.now(timezone.utc), settings.tenant_id)


def _deliver(settings, engine, kernel, client):
    box, sender = Outbox(engine, settings.tenant_id), make_sender(settings, engine)
    return lambda: box.deliver(sender)


JOB_FACTORIES = [
    ("deadline_engine", "0 * * * *", _deadlines),
    ("reminders", "0 * * * *", _reminders),
    ("deliver_outbox", "* * * * *", _deliver),
]
