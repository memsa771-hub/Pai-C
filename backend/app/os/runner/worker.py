"""The OS worker process: `python -m app.os.runner.worker`.

Environment: OS_DATABASE_URL (also the DBOS system database), OS_DBOS_SYSTEM_SCHEMA, OS_WORKER_ID
(required, stable per replica), OS_TENANT_ID, OS_EXTRA_MODULES (tests only: `pkg.mod:NAME,...`),
OS_PARENT_PID (optional: exit when that parent is gone). Stops on SIGTERM/SIGINT.

Besides running DBOS workflows, the main loop is the enqueuer: about once a second it sends the
kernel's unsent enqueue requests to the queue (the reconciler, every 5 minutes, is only the backstop),
and starts the day's research runs for programmes whose facts are waiting (Slice 2, R2-P1). Research runs
only when OS_OPENAI_API_KEY is set; without it, confirm_fact tasks wait for an admin.
"""

import importlib
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from dbos import DBOS, DBOSClient
from sqlalchemy import Engine

from app.os.db import make_engine
from app.os.kernel import Kernel
from app.os.knowledge.profile import PROFILE_DIR, load_profile_dir
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
PROFILE_SOURCE: Path = PROFILE_DIR  # the research profiles, validated at startup
ENQUEUE_EVERY_S = 1.0


def _extra_modules(spec: str) -> list[Module]:
    found = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        module_path, _, name = item.partition(":")
        found.append(getattr(importlib.import_module(module_path), name))
    return found


def register_research_if_configured(settings: OsSettings, engine: Engine, kernel: Kernel) -> bool:
    """Registers os.research (readers built once, before launch). False when no model key is set."""
    if not settings.openai_api_key:
        log.warning("OS_OPENAI_API_KEY is not set: research is off and confirm_fact tasks wait for an admin")
        return False
    from app.os.agents.spec import AGENT_DIR, load_agent_spec  # imported late: only a researching worker needs them
    from app.os.knowledge.research.pages import PageGateway
    from app.os.knowledge.research.readings import build_readers, model_for
    from app.os.knowledge.research.run import register_research
    from app.os.workers.jobs import _service

    spec = load_agent_spec(AGENT_DIR / "research.v1.yaml")
    profiles = load_profile_dir(PROFILE_SOURCE)
    model = model_for(settings, spec.tier)
    readers = {key: build_readers(model, profile, spec) for key, profile in profiles.items()}
    register_research(engine, settings, kernel, _service(settings, engine, kernel),
                      PageGateway(engine, settings.tenant_id, settings), readers, spec, profiles)
    return True


def build(settings: OsSettings) -> tuple[Registry, Kernel, DBOSClient, Engine]:
    registry = default_registry()
    for module in _extra_modules(os.environ.get("OS_EXTRA_MODULES", "")):
        registry.register(module)
    registry.validate(load_playbook_dir(PLAYBOOK_SOURCE).values())  # fail at startup, not on a task (I7)
    load_profile_dir(PROFILE_SOURCE)  # an invalid research profile stops startup too (Slice 2 spec §4.2)
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
    RESEARCH["on"] = register_research_if_configured(settings, engine, kernel)
    return registry, kernel, client, engine


RESEARCH = {"on": False}  # set by build(): whether this worker starts research runs


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
                if RESEARCH["on"]:
                    from app.os.knowledge.research.run import enqueue_research

                    enqueue_research(engine, client, settings.tenant_id, datetime.now(timezone.utc).date())
            except Exception:  # noqa: BLE001  (a database blip must not kill the worker; next tick retries)
                log.exception("enqueue failed")
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
