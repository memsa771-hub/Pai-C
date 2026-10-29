"""PlanService: select playbook -> read facts -> compile -> kernel. Shared by the API and the workers."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date

from sqlalchemy import Engine, and_, select

from app.os import models
from app.os.compiler import PlanDraft, compile_plan, date_of, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Kernel, PlanRef, StaleDraft
from app.os.knowledge import KnowledgePort
from app.os.packs.visa import ADMITTED, REJECTED, VisaChoiceStore, answers, preselect
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

    def compile(self, contract: RouteContract, playbook: Playbook, plan_id: int | None = None,
                extra_overrides: Sequence = ()) -> PlanDraft:
        """`plan_id`: a running plan, whose replan overrides (Slice 7) are applied, so every recompile keeps them.
        `extra_overrides`: a replan's candidate overrides, compiled to check them before they are stored."""
        from app.os.replan.store import OverrideStore  # imported here: replan imports the service

        route_fields, programme_fields = needed_fields(playbook)
        year = contract.target_intake.year
        refs = [p.programme_ref for p in contract.programmes]
        overrides = [*OverrideStore(self.engine, self.kernel.tenant_id).active(plan_id), *extra_overrides]
        return compile_plan(
            contract, playbook,
            self.knowledge.route_facts(playbook.key, sorted(route_fields), year),
            self.knowledge.programme_facts(refs, sorted(programme_fields), year),
            self.today(), self.disabled_types(),
            overrides=overrides, chosen={"visa": self.visa_programme(contract, plan_id, overrides)},
            excluded={"visa": self.not_visa_programmes(contract, plan_id)},
        )

    def not_visa_programmes(self, contract: RouteContract, plan_id: int | None) -> set[str]:
        """Programmes the provisional visa date (no visa programme yet) must not come from: once any programme
        admitted the student, every other one; before that, those that said "not admitted" (still in the plan until
        the removal is accepted). Slice 9 Task 11 fix round 1."""
        if plan_id is None:
            return set()
        said = answers(self.engine, self.kernel.tenant_id, plan_id)
        refs = {p.programme_ref for p in contract.programmes}
        yes = {r for r, a in said.items() if a == ADMITTED and r in refs}
        return refs - yes if yes else {r for r, a in said.items() if a == REJECTED}

    def visa_programme(self, contract: RouteContract, plan_id: int | None, overrides: Sequence = ()) -> str | None:
        """The programme the student's visa file is for: their stored choice, else the one programme that admitted
        them (the visa page's rule, Slice 6b S6b-D8 and Slice 9 Task 11), else None. A removed programme is never
        it. The visa step's date follows its semester start (F1)."""
        if plan_id is None:
            return None
        removed = {o.target for o in overrides if o.op == "cancel_programme"}
        live = tuple(p.programme_ref for p in contract.programmes if p.programme_ref not in removed)
        stored = VisaChoiceStore(self.engine, self.kernel.tenant_id).get(contract.student_ref)
        if stored is not None and stored.programme_ref in live:
            return stored.programme_ref
        return preselect(self.engine, self.kernel.tenant_id, plan_id, among=live)

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
            draft = self.compile(contract, self._pinned(plan_id), plan_id)
            try:
                return self.kernel.revise(plan_id, cause, draft, based_on=sha)
            except StaleDraft:
                continue
        raise StaleDraft(f"plan {plan_id} kept changing during recompile")

    def change_programmes(self, plan_id: int, edit, cause: str) -> int | None:
        """A Slice 4 swap or remove: `edit(contract)` returns the new programme list from the plan's *current*
        contract (it may refuse). It is re-applied on every retry, so a change that landed meanwhile is kept, never
        overwritten (final review). Compiled with the pinned playbook and applied by the kernel."""
        for _ in range(3):
            contract, sha = self._contract(plan_id)
            new = RouteContract.model_validate({**contract.model_dump(mode="json"),
                                                "programmes": [p.model_dump() for p in edit(contract)]})
            draft = self.compile(new, self._pinned(plan_id), plan_id)
            try:
                return self.kernel.change_contract(plan_id, new, draft, cause, based_on=sha)
            except StaleDraft:
                continue
        raise StaleDraft(f"plan {plan_id} kept changing during the programme change")

    def check_newer(self, plan_id: int) -> bool:
        """Records a `playbook_newer` replan event (Slice 7) when a newer playbook exists for the plan's route.
        True when one was recorded now."""
        from app.os.replan import events  # imported here: replan imports the service

        contract, _ = self._contract(plan_id)
        pinned = self._pinned(plan_id)
        newest = select_playbook(self.playbooks, contract.origin_country, contract.destination_country, contract.level)
        if newest.key != pinned.key or newest.version <= pinned.version:
            return False
        with self.engine.begin() as conn:
            return events.record(conn, self.kernel.tenant_id, plan_id, "playbook_newer",
                                 {"playbook": newest.key, "version": newest.version, "from": pinned.version},
                                 f"{newest.key}@{newest.version}") is not None

    def upgrade(self, plan_id: int, version: int | None = None) -> int:
        """Moves a running plan to the newest playbook for its route (parent §4.3), or to `version` (the one the
        student accepted, Slice 7: never a newer one they did not see)."""
        contract, sha = self._contract(plan_id)
        newest = select_playbook(self.playbooks, contract.origin_country, contract.destination_country, contract.level)
        if version is not None:
            newest = self.playbooks[(newest.key, version)]
        return self.kernel.upgrade_playbook(plan_id, self.compile(contract, newest, plan_id), based_on=sha)

    def anchor_fields(self) -> set[str]:
        return {t.anchor.fact for book in self.playbooks.values() for t in book.tasks if t.anchor}

    def check_fact_value(self, field: str, value) -> None:
        """A fact the compiler uses as a date must parse as one, before it is stored (review I3)."""
        if field in self.anchor_fields():
            date_of(value, field)
