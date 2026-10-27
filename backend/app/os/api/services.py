"""Wires the OS services the API needs. Startup fails on an invalid playbook or an unowned task type."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from sqlalchemy import Engine

from app.os import clock
from app.os.adapters.counsellor.escalation import escalation_sink
from app.os.consent import current_terms
from app.os.db import make_engine
from app.os.documents.checks import load_name_variants
from app.os.documents.types import DocumentType, load_document_types
from app.os.kernel import Kernel
from app.os.knowledge import SqlKnowledge
from app.os.playbooks import Playbook, load_playbook_dir
from app.os.ports.escalation import EscalationSink
from app.os.rehearsal.store import install_clock
from app.os.runner import APP_NAME, default_registry
from app.os.service import PlanService
from app.os.settings import OsSettings
from app.os.packs.config import PackConfig, load_pack_configs
from app.os.statements.config import StatementConfig, load_statement_configs


@dataclass(frozen=True)
class Services:
    settings: OsSettings
    engine: Engine
    kernel: Kernel
    knowledge: SqlKnowledge
    plans: PlanService
    dbos_client: Callable[[], object]  # the kernel side's DBOSClient, made on first use (spec §4.8 research trigger)
    today: Callable[[], date]
    document_types: Mapping[str, DocumentType]  # Slice 3: validated at mount, like the playbooks
    name_variants: list[set[str]]
    statement_configs: Mapping[str, StatementConfig] = None  # Slice 5: per route, checked at mount
    pack_configs: Mapping[str, PackConfig] = None  # Slice 6a: per route, checked at mount
    visa_configs: Mapping[str, PackConfig] = None  # Slice 6b: the visa file per route, checked at mount
    escalations: EscalationSink = None  # Slice 8: every support case goes through this port (S8-D12)
    terms_dir: Path | None = None  # Slice 9a: the pilot terms folder; None = app/os/consent (tests pass their own)


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
                  dbos_client: Callable[[], object] | None = None,
                  document_types: Mapping[str, DocumentType] | None = None,
                  statement_configs: Mapping[str, StatementConfig] | None = None,
                  pack_configs: Mapping[str, PackConfig] | None = None,
                  visa_configs: Mapping[str, PackConfig] | None = None,
                  terms_dir: Path | None = None) -> Services:
    engine = engine or make_engine(settings)
    books = playbooks if playbooks is not None else load_playbook_dir()
    registry = default_registry()
    registry.validate(books.values())
    kernel = Kernel(engine, settings.tenant_id)
    knowledge = SqlKnowledge(engine, settings.tenant_id)
    today = today or clock.today
    plans = PlanService(engine, settings, kernel, knowledge, books, today=today, registry=registry)
    types = document_types if document_types is not None else load_document_types()
    current_terms(terms_dir)  # Slice 9a: a missing or broken terms file stops startup (read again on every call)
    install_clock(settings, engine)  # Slice 9a: rehearsal mode reads the stored offset (loud warning); else real time
    return Services(settings, engine, kernel, knowledge, plans, dbos_client or _client_factory(settings), today,
                    types, load_name_variants(),
                    statement_configs if statement_configs is not None else load_statement_configs(),
                    pack_configs if pack_configs is not None else load_pack_configs(),
                    visa_configs if visa_configs is not None else load_pack_configs(kind="visa"),
                    escalation_sink(engine, settings.tenant_id),  # Slice 8: loads the notes, so a bad file stops startup
                    terms_dir)
