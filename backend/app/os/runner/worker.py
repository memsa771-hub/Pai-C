"""The OS worker process: `python -m app.os.runner.worker`.

Environment: OS_DATABASE_URL (also the DBOS system database), OS_DBOS_SYSTEM_SCHEMA, OS_WORKER_ID
(required, stable per replica), OS_TENANT_ID, OS_EXTRA_MODULES (tests only: `pkg.mod:NAME,...`),
OS_PARENT_PID (optional: exit when that parent is gone). Stops on SIGTERM/SIGINT.

Besides running DBOS workflows, the main loop is the enqueuer: about once a second it sends the
kernel's unsent enqueue requests to the queue (the reconciler, every 5 minutes, is only the backstop),
and starts the day's research runs for programmes whose facts are waiting (Slice 2, R2-P1). Research and
document reading (Slice 3; the API enqueues each upload) run only when OS_OPENAI_API_KEY is set; without it,
confirm_fact tasks wait for an admin and uploads stay unread.
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
PACK_SOURCE: Path = Path(__file__).resolve().parents[1] / "packs"  # the pack configs, validated at startup (Slice 6a)
ENQUEUE_EVERY_S = 1.0


def _extra_modules(spec: str) -> list[Module]:
    found = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        module_path, _, name = item.partition(":")
        found.append(getattr(importlib.import_module(module_path), name))
    return found


def register_research_if_configured(settings: OsSettings, engine: Engine, kernel: Kernel) -> bool:
    """Registers os.research (readers built once, before launch). False when no model key is set.

    OS_TEST_RESEARCH_MODEL (tests only, `pkg.mod:factory`) gives a fake model instead, like OS_EXTRA_MODULES."""
    test_model = os.environ.get("OS_TEST_RESEARCH_MODEL", "").strip()
    if not settings.openai_api_key and not test_model:
        log.warning("OS_OPENAI_API_KEY is not set: research is off and confirm_fact tasks wait for an admin")
        return False
    from app.os.agents.spec import AGENT_DIR, load_agent_spec  # imported late: only a researching worker needs them
    from app.os.knowledge.research.pages import PageGateway
    from app.os.knowledge.research.readings import build_readers, model_for
    from app.os.knowledge.research.run import register_research
    from app.os.workers.jobs import _service

    spec = load_agent_spec(AGENT_DIR / "research.v1.yaml")
    profiles = load_profile_dir(PROFILE_SOURCE)
    if test_model:
        module_path, _, name = test_model.partition(":")
        model = getattr(importlib.import_module(module_path), name)()
    else:
        model = model_for(settings, spec.tier)
    readers = {key: build_readers(model, profile, spec) for key, profile in profiles.items()}
    register_research(engine, settings, kernel, _service(settings, engine, kernel),
                      PageGateway(engine, settings.tenant_id, settings), readers, spec, profiles)
    return True


def register_documents_if_configured(settings: OsSettings, engine: Engine) -> bool:
    """Registers os.document (readers built once, before launch). False when no model key is set: uploads then
    stay `uploaded` until a worker with a key runs.

    OS_TEST_DOCUMENT_MODEL (tests only, `pkg.mod:factory`) gives a fake model instead, like OS_TEST_RESEARCH_MODEL."""
    test_model = os.environ.get("OS_TEST_DOCUMENT_MODEL", "").strip()
    if not settings.openai_api_key and not test_model:
        log.warning("OS_OPENAI_API_KEY is not set: documents are not read")
        return False
    from app.os.agents.spec import AGENT_DIR, load_agent_spec  # imported late: only a reading worker needs them
    from app.os.documents.checks import load_name_variants
    from app.os.documents.reader import build_readers
    from app.os.documents.run import register_documents
    from app.os.documents.types import load_document_types
    from app.os.knowledge.research.readings import model_for

    spec = load_agent_spec(AGENT_DIR / "documents.v1.yaml")
    types = load_document_types()
    if test_model:
        module_path, _, name = test_model.partition(":")
        model = getattr(importlib.import_module(module_path), name)()
    else:
        model = model_for(settings, spec.tier)
    register_documents(engine, settings, build_readers(model, types, spec), spec, types, load_name_variants())
    return True


def register_statements_if_configured(settings: OsSettings, engine: Engine) -> bool:
    """Registers os.statement (Writer and Critic built once, before launch). False when no model key is set.
    OS_TEST_STATEMENT_MODEL (tests only, `pkg.mod:factory`) gives a fake model, like the documents worker."""
    test_model = os.environ.get("OS_TEST_STATEMENT_MODEL", "").strip()
    if not settings.openai_api_key and not test_model:
        log.warning("OS_OPENAI_API_KEY is not set: statements are not drafted")
        return False
    from app.os.agents.spec import AGENT_DIR, load_agent_spec  # imported late: only a drafting worker needs them
    from app.os.knowledge.research.readings import model_for
    from app.os.knowledge.store import SqlKnowledge
    from app.os.statements.agents import build_agents
    from app.os.statements.config import load_statement_configs
    from app.os.statements.run import register_statements

    wspec, cspec = load_agent_spec(AGENT_DIR / "writer.v1.yaml"), load_agent_spec(AGENT_DIR / "critic.v1.yaml")
    if test_model:
        module_path, _, name = test_model.partition(":")
        model = getattr(importlib.import_module(module_path), name)()
    else:
        model = model_for(settings, wspec.tier)
    writer, critic = build_agents(model, wspec, cspec)
    register_statements(engine, settings, writer, critic, wspec, cspec, load_statement_configs(),
                        SqlKnowledge(engine, settings.tenant_id))
    return True


def register_packs_always(settings: OsSettings, engine: Engine, books, pack_configs, visa_configs=None) -> None:
    """Registers os.pack (Slice 6a), for packs and visa files (Slice 6b). It needs no model key: both are built by
    rules only (S6a-D5)."""
    from app.os.knowledge.store import SqlKnowledge
    from app.os.packs.run import register_packs
    from app.os.statements.config import load_statement_configs

    register_packs(engine, settings, SqlKnowledge(engine, settings.tenant_id), books, pack_configs,
                   load_statement_configs(), visa_configs)


def register_replan_always(settings: OsSettings, engine: Engine, kernel: Kernel, books) -> object:
    """Registers os.replan (Slice 7). The rules need no model key; the Supervisor is built only with a key (or
    OS_TEST_REPLAN_MODEL, tests only, `pkg.mod:factory`). Without it, what the rules leave goes to the support
    inbox. Returns the Replanner the replan job uses."""
    from app.os.knowledge.store import SqlKnowledge
    from app.os.outbox import Outbox
    from app.os.replan.apply import Replanner
    from app.os.replan.config import load_replan_configs
    from app.os.replan.run import register_replan
    from app.os.service import PlanService

    plans = PlanService(engine, settings, kernel, SqlKnowledge(engine, settings.tenant_id), books,
                        today=lambda: datetime.now(timezone.utc).date())
    replanner = Replanner(engine, plans, load_replan_configs(), Outbox(engine, settings.tenant_id))
    supervisor = None
    test_model = os.environ.get("OS_TEST_REPLAN_MODEL", "").strip()
    if settings.openai_api_key or test_model:
        from app.os.agents.spec import AGENT_DIR, load_agent_spec
        from app.os.knowledge.research.readings import model_for
        from app.os.replan.supervisor import build_supervisor

        spec = load_agent_spec(AGENT_DIR / "supervisor.v1.yaml")
        if test_model:
            module_path, _, name = test_model.partition(":")
            model = getattr(importlib.import_module(module_path), name)()
        else:
            model = model_for(settings, spec.tier)
        supervisor = (build_supervisor(model, spec), spec)
    else:
        log.warning("OS_OPENAI_API_KEY is not set: replan hand-overs go to the support inbox")
    register_replan(engine, settings, replanner, supervisor)
    return replanner


def build(settings: OsSettings) -> tuple[Registry, Kernel, DBOSClient, Engine]:
    registry = default_registry()
    for module in _extra_modules(os.environ.get("OS_EXTRA_MODULES", "")):
        registry.register(module)
    books = load_playbook_dir(PLAYBOOK_SOURCE)
    registry.validate(books.values())  # fail at startup, not on a task (I7)
    profiles = load_profile_dir(PROFILE_SOURCE)  # an invalid research profile stops startup too (Slice 2 spec §4.2)
    from app.os.documents.types import load_document_types  # imported late: keeps the worker's import graph small
    from app.os.packs.config import load_checked_pack_configs

    types = load_document_types()  # so does an invalid document type (Slice 3 spec S3-D2)
    pack_configs = load_checked_pack_configs(PACK_SOURCE, types, books, profiles)  # and an invalid pack config (S6a-D12)
    visa_configs = load_checked_pack_configs(PACK_SOURCE, types, books, profiles, kind="visa")  # or visa file (S6b-D3)
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
    if register_documents_if_configured(settings, engine):
        from app.os.documents.run import retry_waiting

        register_job("documents_retry", "10 0 * * *",  # uploads that waited for the budget, daily at 00:10 UTC
                     lambda: retry_waiting(engine, client, settings.tenant_id, datetime.now(timezone.utc).date()))
    register_statements_if_configured(settings, engine)
    register_packs_always(settings, engine, books, pack_configs, visa_configs)
    replanner = register_replan_always(settings, engine, kernel, books)
    from app.os.replan.run import run_replan_job

    register_job("replan", "*/5 * * * *", lambda: run_replan_job(replanner, client, datetime.now(timezone.utc)))
    from app.os.adapters.counsellor.run import IntakeDeps, register_intake, run_intake_job

    register_intake(IntakeDeps(engine, kernel, replanner.plans, replanner.escalations))  # Slice 8: off by default
    register_job("counsellor_intake", "* * * * *", lambda: run_intake_job(engine, settings.tenant_id, client))
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
