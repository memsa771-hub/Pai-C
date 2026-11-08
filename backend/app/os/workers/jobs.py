"""Scheduled jobs the worker registers: hourly deadline engine and reminders, outbox delivery every minute,
and the daily freshness sweeper (Slice 2 spec §4.7)."""


from app.os import clock
from app.os.knowledge import SqlKnowledge
from app.os.outbox import Outbox, make_sender
from app.os.playbooks import load_playbook_dir
from app.os.service import PlanService
from app.os.workers import deadline_engine, freshness
from app.os.workers.reminders import run_reminders


def _service(settings, engine, kernel) -> PlanService:
    return PlanService(engine, settings, kernel, SqlKnowledge(engine, settings.tenant_id), load_playbook_dir(),
                       today=clock.today)


def _deadlines(settings, engine, kernel, client):
    svc = _service(settings, engine, kernel)
    return lambda: deadline_engine.run(svc, engine)


def _reminders(settings, engine, kernel, client):
    box = Outbox(engine, settings.tenant_id)
    return lambda: run_reminders(engine, box, clock.now(), settings.tenant_id)


def _deliver(settings, engine, kernel, client):
    """The worker's recipient lookup was set from OS_RECIPIENT_LOOKUP by the runner's build(), before this runs."""
    from app.os.ports import recipients

    box, sender = Outbox(engine, settings.tenant_id), make_sender(settings, engine, lookup=recipients.current())
    return lambda: box.deliver(sender)


def _freshness(settings, engine, kernel, client):
    svc = _service(settings, engine, kernel)
    return lambda: freshness.run(svc, engine, clock.now())


def _monitor(settings, engine, kernel, client):
    """P2-T7: season monitoring (OS_MONITOR=1). With the flag off there is no job: nothing is scheduled or ticked."""
    if not settings.monitor:
        return None
    from app.os.knowledge.changes import after_fact_change
    from app.os.knowledge.research.pages import PageGateway
    from app.os.knowledge.review import ReviewQueue
    from app.os.knowledge.sources.snapshots import SnapshotStore
    from app.os.monitor import run as monitor
    from app.os.runner.worker import _source_guard

    tenant = settings.tenant_id
    svc = _service(settings, engine, kernel)
    gateway = PageGateway(engine, tenant, settings, sources=_source_guard(settings, engine, kernel))
    snapshots = SnapshotStore(engine, tenant, max_bytes=settings.page_max_bytes)
    queue = ReviewQueue(engine, tenant, svc.knowledge)

    def changed(scope, ref, field, fact_id, status, intake_year) -> None:
        after_fact_change(svc, kernel, scope, ref, field, fact_id, status, intake_year, complete=False)

    return lambda: monitor.run(engine, tenant, clock.today(), clock.now(), gateway=gateway, snapshots=snapshots,
                               knowledge=svc.knowledge, queue=queue, after_change=changed)


JOB_FACTORIES = [
    ("deadline_engine", "0 * * * *", _deadlines),
    ("reminders", "0 * * * *", _reminders),
    ("deliver_outbox", "* * * * *", _deliver),
    ("freshness", "0 3 * * *", _freshness),  # schedule os.freshness, daily at 03:00 UTC
    ("monitor", "30 3 * * *", _monitor),  # schedule os.monitor, daily at 03:30 UTC (P2-T7; off without OS_MONITOR)
]
