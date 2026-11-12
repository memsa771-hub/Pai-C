"""PlanService: select playbook -> read facts -> compile -> kernel. Shared by the API and the workers."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date

from sqlalchemy import Engine, and_, select

from app.os import models
from app.os.compiler import PlanDraft, compile_plan, date_of, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.contracts.route_contract_v2 import RouteContractV2
from app.os.intakes import IntakeNotOpen, IntakeStore
from app.os.kernel import Kernel, PlanRef, StaleDraft
from app.os.knowledge import KnowledgePort, merit
from app.os.packs.visa import ADMITTED, REJECTED, VisaChoiceStore, answers, preselect
from app.os.playbooks import Playbook, PlaybookError, select_playbook
from app.os.requests import gate, state
from app.os.runner import Registry, default_registry
from app.os.settings import OsSettings


class NothingNewer(ValueError):
    """An upgrade to "the newest" playbook found none newer than the one the plan is pinned to."""


def _intake_of(contract: RouteContract | RouteContractV2) -> tuple[str, int]:
    return contract.target_intake.term, contract.target_intake.year


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

    def _existing_plan(self, contract: RouteContract | RouteContractV2) -> int | None:
        P = models.plans
        with self.engine.connect() as conn:
            return conn.execute(select(P.c.id).where(and_(
                P.c.tenant_id == self.kernel.tenant_id, P.c.source == contract.source,
                P.c.external_ref == contract.external_ref))).scalar_one_or_none()

    def compile(self, contract: RouteContract | RouteContractV2, playbook: Playbook, plan_id: int | None = None,
                extra_overrides: Sequence = ()) -> PlanDraft:
        """`plan_id`: a running plan, whose replan overrides (Slice 7) are applied, so every recompile keeps them.
        `extra_overrides`: a replan's candidate overrides, compiled to check them before they are stored."""
        from app.os.replan.store import OverrideStore  # imported here: replan imports the service

        route_fields, programme_fields = needed_fields(playbook)
        year = contract.target_intake.year
        refs = [p.programme_ref for p in contract.programmes]
        overrides = [*OverrideStore(self.engine, self.kernel.tenant_id).active(plan_id), *extra_overrides]
        student = state.build(self, contract.student_ref) if playbook.declares_needs else None  # P1-T8: gate off = None
        # P2-D24: while the plan's intake is open and not yet current, a key with no fact for it reads the newest earlier
        # year's fact, labelled. No registered intake (or none open): the strict read, exactly as before.
        # The fallback reads one earlier year: the year of the intake this one was opened from, else the year before.
        term = contract.target_intake.term
        source = IntakeStore(self.engine, self.kernel.tenant_id).fallback_year(term, year)
        read = ({"intake_term": term, "fallback_previous": True, "fallback_year": source}
                if source is not None else {})
        from app.os.monitor.reports import for_student  # imported here: the report module imports the review queue

        route_facts, programme_facts = for_student(  # owner ruling 2026-11-08: a reported fact holds only the reporters' steps
            self.engine, self.kernel.tenant_id, contract.student_ref,
            self.knowledge.route_facts(playbook.key, sorted(route_fields), year, **read),
            self.knowledge.programme_facts(refs, sorted(programme_fields), year, **read))
        return compile_plan(
            contract, playbook, route_facts, programme_facts,
            self.today(), self.disabled_types(),
            overrides=overrides, chosen={"visa": self.visa_programme(contract, plan_id, overrides)},
            excluded={"visa": self.not_visa_programmes(contract, plan_id)}, student=student,
        )

    def needs_gate(self, contract: RouteContract | RouteContractV2, with_needs: bool | None = None) -> bool:
        """Whether a playbook that declares `needs` may be chosen for this student (P1-T8, D-w1, D-w3): the student's
        needs gate is on. `with_needs` given by the caller wins. The gate is asked only when such a playbook is loaded
        for the route, so a process with none makes no extra call."""
        if with_needs is not None:
            return with_needs
        route = (contract.origin_country, contract.destination_country, contract.level)
        if not any(b.declares_needs and (b.route.origin, b.route.destination, b.route.level) == route
                   for b in self.playbooks.values()):
            return False
        return gate.on(contract.student_ref, engine=self.engine, tenant_id=self.kernel.tenant_id) is not None

    def not_visa_programmes(self, contract: RouteContract | RouteContractV2, plan_id: int | None) -> set[str]:
        """Programmes the provisional visa date (no visa programme yet) must not come from: once any programme
        admitted the student, every other one; before that, those that said "not admitted" (still in the plan until
        the removal is accepted). Slice 9 Task 11 fix round 1."""
        if plan_id is None:
            return set()
        said = answers(self.engine, self.kernel.tenant_id, plan_id)
        refs = {p.programme_ref for p in contract.programmes}
        yes = {r for r, a in said.items() if a == ADMITTED and r in refs}
        return refs - yes if yes else {r for r, a in said.items() if a == REJECTED}

    def visa_programme(self, contract: RouteContract | RouteContractV2, plan_id: int | None, overrides: Sequence = ()) -> str | None:
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

    def start_plan(self, contract: RouteContract | RouteContractV2, *, with_needs: bool | None = None) -> PlanRef:
        """A new plan uses the newest playbook for its route; an existing plan keeps its pinned version.
        `with_needs`: the student's needs gate is on, so a playbook that declares `needs` may be chosen (P1-T8); left
        out, the gate is asked."""
        existing = self._existing_plan(contract)
        term, year = _intake_of(contract)
        if existing is None and not IntakeStore(self.engine, self.kernel.tenant_id).plannable(term, year):  # R-63
            raise IntakeNotOpen(f"the {term} {year} intake is not open for planning yet")
        playbook = (self._pinned(existing) if existing is not None else select_playbook(
            self.playbooks, contract.origin_country, contract.destination_country, contract.level,
            with_needs=self.needs_gate(contract, with_needs), intake=_intake_of(contract)))
        return self.kernel.create_plan(contract, self.compile(contract, playbook))

    def _contract(self, plan_id: int) -> tuple[RouteContract | RouteContractV2, str]:
        P = models.plans
        with self.engine.connect() as conn:
            row = conn.execute(select(P.c.contract, P.c.contract_sha256).where(
                P.c.id == plan_id, P.c.tenant_id == self.kernel.tenant_id)).first()
        if row is None:
            raise KeyError(f"plan {plan_id}")
        # the stored contract_version picks the class: a v1 plan keeps parsing as v1 (D-u)
        cls = RouteContractV2 if row.contract.get("contract_version") == "2" else RouteContract
        return cls.model_validate(row.contract), row.contract_sha256

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
            new = type(contract).model_validate({**contract.model_dump(mode="json"),
                                                "programmes": [p.model_dump() for p in edit(contract)]})
            draft = self.compile(new, self._pinned(plan_id), plan_id)
            try:
                return self.kernel.change_contract(plan_id, new, draft, cause, based_on=sha)
            except StaleDraft:
                continue
        raise StaleDraft(f"plan {plan_id} kept changing during the programme change")

    def check_newer(self, plan_id: int, *, with_needs: bool | None = None) -> bool:
        """Records a `playbook_newer` replan event (Slice 7) when a newer playbook exists for the plan's route.
        True when one was recorded now."""
        from app.os.replan import events  # imported here: replan imports the service

        contract, _ = self._contract(plan_id)
        pinned = self._pinned(plan_id)
        newest = select_playbook(self.playbooks, contract.origin_country, contract.destination_country, contract.level,
                                 with_needs=self.needs_gate(contract, with_needs), intake=_intake_of(contract))
        if newest.key != pinned.key or newest.version <= pinned.version:
            return False
        with self.engine.begin() as conn:
            return events.record(conn, self.kernel.tenant_id, plan_id, "playbook_newer",
                                 {"playbook": newest.key, "version": newest.version, "from": pinned.version},
                                 f"{newest.key}@{newest.version}") is not None

    def upgrade(self, plan_id: int, version: int | None = None, *, with_needs: bool | None = None) -> int:
        """Moves a running plan to the newest playbook for its route (parent §4.3), or to `version` (the one the
        student accepted, Slice 7: never a newer one they did not see)."""
        contract, sha = self._contract(plan_id)
        newest = select_playbook(self.playbooks, contract.origin_country, contract.destination_country, contract.level,
                                 with_needs=self.needs_gate(contract, with_needs), intake=_intake_of(contract))
        if version is not None:
            newest = self.playbooks[(newest.key, version)]
            applies = newest.applies_to  # R-65: a version for other intakes is never forced onto this plan
            if applies is not None and not applies.covers(*_intake_of(contract)):
                raise ValueError(f"playbook {newest.key}@{version} does not cover the {_intake_of(contract)[0]} "
                                 f"{_intake_of(contract)[1]} intake of plan {plan_id}")
        else:  # the newest the gate lets through may be older than the pin (a v2 plan, the gate off): never go back
            pinned = self._pinned(plan_id)
            if newest.key == pinned.key and newest.version <= pinned.version:
                raise NothingNewer(f"plan {plan_id} already uses {pinned.key}@{pinned.version}: nothing newer")
        return self.kernel.upgrade_playbook(plan_id, self.compile(contract, newest, plan_id), based_on=sha)

    def anchor_fields(self) -> set[str]:
        return {t.anchor.fact for book in self.playbooks.values() for t in book.tasks if t.anchor}

    def check_fact_value(self, field: str, value) -> None:
        """A fact the compiler uses as a date must parse as one, before it is stored (review I3)."""
        if field in self.anchor_fields():
            date_of(value, field)
        merit.check_value(field, value)  # P2-T10: a merit formula or closing merit has its shape (R-31)
