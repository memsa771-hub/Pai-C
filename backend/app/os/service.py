"""PlanService: select playbook -> read facts -> compile -> kernel. Shared by the API and the workers."""

from collections.abc import Callable, Mapping
from datetime import date

from sqlalchemy import Engine, and_, select

from app.os import models
from app.os.compiler import PlanDraft, compile_plan, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Kernel, PlanRef
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
        with self.engine.connect() as conn:
            pin = conn.execute(select(models.playbook_pins).where(models.playbook_pins.c.plan_id == plan_id)).one()
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

    def recompile(self, plan_id: int, cause: str) -> int | None:
        with self.engine.connect() as conn:
            raw = conn.execute(select(models.plans.c.contract).where(models.plans.c.id == plan_id)).scalar_one()
        return self.kernel.revise(plan_id, cause, self.compile(RouteContract.model_validate(raw), self._pinned(plan_id)))

    def upgrade(self, plan_id: int) -> int:
        """Moves a running plan to the newest playbook for its route (parent §4.3)."""
        with self.engine.connect() as conn:
            raw = conn.execute(select(models.plans.c.contract).where(models.plans.c.id == plan_id)).scalar_one()
        contract = RouteContract.model_validate(raw)
        newest = select_playbook(self.playbooks, contract.origin_country, contract.destination_country, contract.level)
        return self.kernel.upgrade_playbook(plan_id, self.compile(contract, newest))
