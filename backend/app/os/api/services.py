"""Wires the OS services the API needs. Startup fails on an invalid playbook or an unowned task type."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import cache

from sqlalchemy import Engine

from app.os.db import make_engine
from app.os.kernel import Kernel
from app.os.knowledge import SqlKnowledge
from app.os.playbooks import Playbook, load_playbook_dir
from app.os.runner import APP_NAME, default_registry
from app.os.service import PlanService
from app.os.settings import OsSettings


@dataclass(frozen=True)
class Services:
    settings: OsSettings
    engine: Engine
    kernel: Kernel
    knowledge: SqlKnowledge
    plans: PlanService
    dbos_client: Callable[[], object]  # the kernel side's DBOSClient, made on first use (spec §4.8 research trigger)
    today: Callable[[], date]


def _client_factory(settings: OsSettings) -> Callable[[], object]:
    @cache
    def client():
        from dbos import DBOSClient

        return DBOSClient(system_database_url=settings.database_url, dbos_system_schema=settings.dbos_system_schema,
                          application_name=APP_NAME, lazy=True)

    return client


def make_services(settings: OsSettings, *, engine: Engine | None = None,
                  playbooks: Mapping[tuple[str, int], Playbook] | None = None,
                  today: Callable[[], date] | None = None,
                  dbos_client: Callable[[], object] | None = None) -> Services:
    engine = engine or make_engine(settings)
    books = playbooks if playbooks is not None else load_playbook_dir()
    registry = default_registry()
    registry.validate(books.values())
    kernel = Kernel(engine, settings.tenant_id)
    knowledge = SqlKnowledge(engine, settings.tenant_id)
    today = today or (lambda: datetime.now(timezone.utc).date())
    plans = PlanService(engine, settings, kernel, knowledge, books, today=today, registry=registry)
    return Services(settings, engine, kernel, knowledge, plans, dbos_client or _client_factory(settings), today)
