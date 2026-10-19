"""The OS worker process: `python -m app.os.runner.worker`.

Environment: OS_DATABASE_URL (also the DBOS system database), OS_DBOS_SYSTEM_SCHEMA, OS_WORKER_ID
(required, stable per replica), OS_TENANT_ID, OS_EXTRA_MODULES (tests only: `pkg.mod:NAME,...`),
OS_PARENT_PID (optional: exit when that parent is gone). Stops on SIGTERM/SIGINT.

Besides running DBOS workflows, the main loop is the enqueuer: about once a second it sends the
kernel's unsent enqueue requests to the queue (the reconciler, every 5 minutes, is only the backstop).
"""

import importlib
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from dbos import DBOS, DBOSClient
from sqlalchemy import Engine

from app.os.db import make_engine
from app.os.kernel import Kernel
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.runner.enqueue import enqueue_pending
from app.os.runner.modules import default_registry
from app.os.runner.reconcile import reconcile
from app.os.runner.registry import Module, Registry
from app.os.runner.workflow import APP_NAME, dbos_config, launch, register_job, register_workflow
from app.os.settings import OsSettings, load_settings

log = logging.getLogger("app.os.worker")

# Extra scheduled jobs (name, cron, factory(settings, engine, kernel, client) -> fn).
JOB_FACTORIES: list[tuple[str, str, Callable]] = []
PLAYBOOK_SOURCE: Path = PLAYBOOK_DIR  # the playbooks every task type must have an owner for
ENQUEUE_EVERY_S = 1.0


def _extra_modules(spec: str) -> list[Module]:
    found = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        module_path, _, name = item.partition(":")
        found.append(getattr(importlib.import_module(module_path), name))
    return found


def build(settings: OsSettings) -> tuple[Registry, Kernel, DBOSClient, Engine]:
    registry = default_registry()
    for module in _extra_modules(os.environ.get("OS_EXTRA_MODULES", "")):
        registry.register(module)
    registry.validate(load_playbook_dir(PLAYBOOK_SOURCE).values())  # fail at startup, not on a task (I7)
    engine = make_engine(settings)
    kernel = Kernel(engine, settings.tenant_id)
    DBOS(config=dbos_config(settings, settings.worker_id))
    register_workflow(engine, settings, registry, kernel)
    client = DBOSClient(system_database_url=settings.database_url, dbos_system_schema=settings.dbos_system_schema,
                        application_name=APP_NAME, lazy=True)
    register_job("reconcile", "*/5 * * * *", lambda: reconcile(engine, client, kernel))
    from app.os.workers.jobs import JOB_FACTORIES as worker_jobs  # imported late: workers depend on the runner

    for name, cron, factory in [*worker_jobs, *JOB_FACTORIES]:
        register_job(name, cron, factory(settings, engine, kernel, client))
    return registry, kernel, client, engine


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    if not settings.worker_id or settings.worker_id == "local":
        print("OS_WORKER_ID must be set to a stable, unique worker ID (not 'local')", file=sys.stderr)
        return 2
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    parent = int(os.environ["OS_PARENT_PID"]) if os.environ.get("OS_PARENT_PID") else None
    _, _, client, engine = build(settings)
    launch()
    try:
        while not stop.wait(ENQUEUE_EVERY_S):
            if parent is not None and os.getppid() != parent:
                break  # the parent died without stopping us: do not linger
            try:
                enqueue_pending(engine, client, settings.tenant_id)
            except Exception:  # noqa: BLE001  (a database blip must not kill the worker; next tick retries)
                log.exception("enqueue_pending failed")
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
