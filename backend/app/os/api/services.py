"""Wires the OS services the API needs. Startup fails on an invalid playbook or an unowned task type."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import Engine

from app.os.db import make_engine
from app.os.kernel import Kernel
from app.os.knowledge import SqlKnowledge
from app.os.playbooks import Playbook, load_playbook_dir
from app.os.runner import default_registry
from app.os.service import PlanService
from app.os.settings import OsSettings


@dataclass(frozen=True)
class Services:
    settings: OsSettings
    engine: Engine
    kernel: Kernel
    knowledge: SqlKnowledge
    plans: PlanService


def make_services(settings: OsSettings, *, engine: Engine | None = None,
                  playbooks: Mapping[tuple[str, int], Playbook] | None = None,
                  today: Callable[[], date] | None = None) -> Services:
    engine = engine or make_engine(settings)
    books = playbooks if playbooks is not None else load_playbook_dir()
    registry = default_registry()
    registry.validate(books.values())
    kernel = Kernel(engine, settings.tenant_id)
    knowledge = SqlKnowledge(engine, settings.tenant_id)
    plans = PlanService(engine, settings, kernel, knowledge, books,
                        today=today or (lambda: datetime.now(timezone.utc).date()), registry=registry)
    return Services(settings, engine, kernel, knowledge, plans)
