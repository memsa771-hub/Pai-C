"""PlanService: select playbook -> read facts -> compile -> kernel. Shared by the API and the workers."""

from collections.abc import Callable, Mapping
from datetime import date

from sqlalchemy import Engine, and_, select

from app.os import models
from app.os.compiler import PlanDraft, compile_plan, date_of, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Kernel, PlanRef, StaleDraft
from app.os.knowledge import KnowledgePort
from app.os.playbooks import Playbook, PlaybookError, select_playbook
from app.os.runner import Registry, default_registry
from app.os.settings import OsSettings


class PlanService:
    def __init__(self, engine: Engine, settings: OsSettings, kernel: Kernel, knowledge: KnowledgePort,
                 playbooks: Mapping[tuple[str, int], Playbook], today: Callable[[], date],
                 registry: Registry | None = None) -> None:
        self.engine = engine
        self.settings = settings
        self.kernel = kernel
        self.knowledge = knowledge
        self.playbooks = playbooks
        self.today = today
        self.registry = registry or default_registry()

    def disabled_types(self) -> frozenset[str]:
        with self.engine.connect() as conn:
            names = conn.execute(select(models.modules.c.module).where(
                models.modules.c.tenant_id == self.kernel.tenant_id, models.modules.c.enabled.is_(False),
            )).scalars().all()
        return self.registry.types_of(names)

    def _pinned(self, plan_id: int) -> Playbook:
        pins = models.playbook_pins
        with self.engine.connect() as conn:
            pin = conn.execute(select(pins).where(
                pins.c.plan_id == plan_id, pins.c.tenant_id == self.kernel.tenant_id)).first()
        if pin is None:
            raise KeyError(f"plan {plan_id}")
        try:
            return self.playbooks[(pin.playbook_key, pin.version)]
        except KeyError:
            raise PlaybookError(f"pinned playbook {pin.playbook_key} v{pin.version} is not loaded") from None

    def _existing_plan(self, contract: RouteContract) -> int | None:
        P = models.plans
        with self.engine.connect() as conn:
            return conn.execute(select(P.c.id).where(and_(
                P.c.tenant_id == self.kernel.tenant_id, P.c.source == contract.source,
                P.c.external_ref == contract.external_ref))).scalar_one_or_none()

    def compile(self, contract: RouteContract, playbook: Playbook) -> PlanDraft:
        route_fields, programme_fields = needed_fields(playbook)
        year = contract.target_intake.year
        refs = [p.programme_ref for p in contract.programmes]
        return compile_plan(
            contract, playbook,
            self.knowledge.route_facts(playbook.key, sorted(route_fields), year),
            self.knowledge.programme_facts(refs, sorted(programme_fields), year),
            self.today(), self.disabled_types(),
        )

    def start_plan(self, contract: RouteContract) -> PlanRef:
        """A new plan uses the newest playbook for its route; an existing plan keeps its pinned version."""
        existing = self._existing_plan(contract)
        playbook = (self._pinned(existing) if existing is not None else select_playbook(
            self.playbooks, contract.origin_country, contract.destination_country, contract.level))
        return self.kernel.create_plan(contract, self.compile(contract, playbook))

    def _contract(self, plan_id: int) -> tuple[RouteContract, str]:
        P = models.plans
        with self.engine.connect() as conn:
            row = conn.execute(select(P.c.contract, P.c.contract_sha256).where(
                P.c.id == plan_id, P.c.tenant_id == self.kernel.tenant_id)).first()
        if row is None:
            raise KeyError(f"plan {plan_id}")
        return RouteContract.model_validate(row.contract), row.contract_sha256

    def recompile(self, plan_id: int, cause: str) -> int | None:
        """Compiles outside the lock, then revises only if the contract is still the one compiled from
        (StaleDraft otherwise: recompile from the new contract, a few times at most)."""
        for _ in range(3):
            contract, sha = self._contract(plan_id)
            draft = self.compile(contract, self._pinned(plan_id))
            try:
                return self.kernel.revise(plan_id, cause, draft, based_on=sha)
            except StaleDraft:
                continue
        raise StaleDraft(f"plan {plan_id} kept changing during recompile")

    def upgrade(self, plan_id: int) -> int:
        """Moves a running plan to the newest playbook for its route (parent §4.3)."""
        contract, sha = self._contract(plan_id)
        newest = select_playbook(self.playbooks, contract.origin_country, contract.destination_country, contract.level)
        return self.kernel.upgrade_playbook(plan_id, self.compile(contract, newest), based_on=sha)

    def anchor_fields(self) -> set[str]:
        return {t.anchor.fact for book in self.playbooks.values() for t in book.tasks if t.anchor}

    def check_fact_value(self, field: str, value) -> None:
        """A fact the compiler uses as a date must parse as one, before it is stored (review I3)."""
        if field in self.anchor_fields():
            date_of(value, field)
