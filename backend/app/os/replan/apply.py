"""Deciding and applying replan proposals (Slice 7 spec S7-D5..D10). Plan state changes only through the kernel
(invariant 1): overrides are stored, then the plan is recompiled with them and applied as a kernel revision.

Every write is keyed by the proposal, and a proposal is keyed by its event, so a repeated step or workflow finds
its work already done (invariant 8)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import TypeAdapter
from sqlalchemy import Engine, func, select

from app.os import models
from app.os.kernel import IllegalTransition, StaleDraft
from app.os.replan.checks import check_operations, task_rows
from app.os.replan.config import ReplanConfig
from app.os.replan.events import Event
from app.os.replan.ops import (
    Escalate, Op, Ops, RequestFromStudent, SwapProgramme, UpgradePlaybook, is_big, to_overrides,
)
from app.os.replan.rules import PlanState
from app.os.replan.store import OverrideStore, ProposalStore, SupportStore

EXPIRY = timedelta(days=7)
BEFORE_DEADLINE = timedelta(days=1)
MIN_EXPIRY = timedelta(hours=1)
DAILY_REVISIONS = 3  # replan revisions per plan per UTC day; the 4th pauses changes (S7-D9)
LIMIT_REASON = "Changes are paused: this plan reached today's limit of 3 automatic changes."
_OPS = TypeAdapter(Ops)


class ProposalStale(ValueError):
    """The proposal can no longer be accepted: answered, expired, or the plan changed so that it no longer fits."""


@dataclass(frozen=True)
class Decision:
    status: str  # applied | pending | refused | paused | support
    proposal_id: int | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ops_of(raw: list[dict]) -> list[Op]:
    return list(_OPS.validate_python(raw))


def _writes(op: Op) -> bool:
    """Whether the operation makes a plan revision (and so counts towards the daily limit)."""
    return bool(to_overrides(op)) or isinstance(op, (SwapProgramme, UpgradePlaybook))


class Replanner:
    def __init__(self, engine: Engine, plans, configs: Mapping[str, ReplanConfig], outbox,
                 clock: Callable[[], datetime] = _utcnow) -> None:
        self.engine, self.plans, self.configs, self.outbox, self.clock = engine, plans, configs, outbox, clock
        self.tenant = plans.kernel.tenant_id
        self.proposals, self.overrides = ProposalStore(engine, self.tenant), OverrideStore(engine, self.tenant)
        self.support_cases = SupportStore(engine, self.tenant)

    # ------------------------------------------------------------------ state

    def config(self, plan_id: int) -> ReplanConfig:
        return self.configs.get(self.plans._pinned(plan_id).key, ReplanConfig())

    def student_of(self, plan_id: int) -> str:
        with self.engine.connect() as conn:
            return conn.execute(select(models.plans.c.student_ref).where(models.plans.c.id == plan_id)).scalar_one()

    def state(self, plan_id: int, with_suggestions: bool = False) -> PlanState:
        contract, _ = self.plans._contract(plan_id)
        book = self.plans._pinned(plan_id)
        tasks = task_rows(self.engine, self.tenant, plan_id)
        programmes = [p.programme_ref for p in sorted(contract.programmes, key=lambda p: p.rank)]
        suggestions = {ref: self._suggestions(contract, book, ref) for ref in programmes} if with_suggestions else {}
        return PlanState(plan_id, book.key, programmes, tasks, suggestions, book.version)

    def _suggestions(self, contract, book, ref: str) -> list[str]:
        """Up to 3 programmes on the route the student likely meets, not in the plan, most confirmed facts first."""
        from app.os.eligibility.notes import profile_of, programme_cards
        from app.os.knowledge.requests import visible_programmes

        year, chosen = contract.target_intake.year, {p.programme_ref for p in contract.programmes}
        others = [p.ref for p in visible_programmes(self.engine, self.tenant, book.key, year) if p.ref not in chosen]
        if not others or book.eligibility is None:
            return [r for r in others if self.confirmed(r, year)][:3]
        cards = programme_cards(self.plans, book.eligibility, others, year, profile_of(self.plans, contract.student_ref))
        good = [(-n, r) for r, (card, n) in cards.items() if card.verdict == "likely_meets"]
        return [r for _, r in sorted(good)][:3]

    def confirmed(self, ref: str, year: int) -> bool:
        F = models.knowledge_facts
        with self.engine.connect() as conn:
            return bool(conn.execute(select(func.count()).select_from(F).where(
                F.c.tenant_id == self.tenant, F.c.scope == "programme", F.c.ref == ref, F.c.intake_year == year,
                F.c.status == "confirmed")).scalar())

    def check(self, plan_id: int, ops: list[Op]) -> tuple[list[Op], list[dict]]:
        contract, _ = self.plans._contract(plan_id)
        book = self.plans._pinned(plan_id)

        def compile_with(candidate: list[Op]):
            return self.plans.compile(contract, book, plan_id, [o for op in candidate for o in to_overrides(op)])

        year = contract.target_intake.year
        return check_operations(ops, task_rows(self.engine, self.tenant, plan_id), book, compile_with,
                                compile_with([]), lambda ref: self.confirmed(ref, year))

    def _expires(self, plan_id: int, ops: list[Op]) -> datetime:
        """7 days, or 1 day before the earliest deadline among the steps the proposal touches (never under 1 h)."""
        now, tasks = self.clock(), task_rows(self.engine, self.tenant, plan_id)
        touched = set()
        for op in ops:
            for attr in ("instance_key", "before"):
                if hasattr(op, attr):
                    touched.add(getattr(op, attr))
            for attr in ("programme_ref", "out_ref"):
                ref = getattr(op, attr, None)
                if ref:
                    touched |= {k for k, t in tasks.items() if t.programme_ref == ref}
        dates = [tasks[k].latest_finish for k in touched if k in tasks and tasks[k].latest_finish is not None]
        at = min([now + EXPIRY, *[d - BEFORE_DEADLINE for d in dates]])
        return max(at, now + MIN_EXPIRY)

    # ------------------------------------------------------------------ deciding

    def decide(self, plan_id: int, event_ids: list[int], source: str, ops: list[Op]) -> Decision:
        """Checks the operations and either applies them (small), proposes them (big), or opens a support case."""
        existing = self.proposals.for_event(event_ids[0])
        if existing is not None:  # a repeated step: finish what it started
            if existing.status == "applied" and existing.revision is None and existing.ops:
                self.apply(existing.id, "applied")
            return Decision(existing.status, existing.id)
        if self.plans.kernel.changes_paused(plan_id):
            return Decision("paused")
        kept, refused = self.check(plan_id, ops)
        kept = kept[:10]
        if ops and not kept:
            pid = self.proposals.create(plan_id, event_ids, source, [], refused, big=False, expires_at=None,
                                        status="refused")
            self.support(plan_id, event_ids, "Every proposed change was refused by the plan's checks.", pid)
            return Decision("refused", pid)
        tasks = task_rows(self.engine, self.tenant, plan_id)
        book = self.plans._pinned(plan_id)
        big = any(is_big(op, tasks, book) for op in kept)
        raw = [op.model_dump(mode="json") for op in kept]
        if big:
            pid = self.proposals.create(plan_id, event_ids, source, raw, refused, big=True,
                                        expires_at=self._expires(plan_id, kept))
            return Decision("pending", pid)
        if any(_writes(op) for op in kept) and self.plans.kernel.replan_revisions_today(plan_id) >= DAILY_REVISIONS:
            pid = self.proposals.create(plan_id, event_ids, source, raw, refused, big=False, expires_at=None,
                                        status="refused")
            self.plans.kernel.set_changes_paused(plan_id, True)
            self.support(plan_id, event_ids, LIMIT_REASON, pid)
            return Decision("paused", pid)
        pid = self.proposals.create(plan_id, event_ids, source, raw, refused, big=False, expires_at=None,
                                    status="applied")
        if kept:
            self.apply(pid, "applied")
        return Decision("applied", pid)

    def close(self, plan_id: int, event_ids: list[int]) -> int:
        """Marks events handled with nothing to change (an empty, applied proposal)."""
        existing = self.proposals.for_event(event_ids[0])
        if existing is not None:
            return existing.id
        return self.proposals.create(plan_id, event_ids, "rules", [], [], big=False, expires_at=None, status="applied")

    def support(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        found = self.support_cases.for_event(event_ids[0]) if event_ids else None
        if found is not None:
            return found.id
        return self.support_cases.open(plan_id, self.student_of(plan_id), reason, event_ids, proposal_id)

    # ------------------------------------------------------------------ applying

    def apply(self, proposal_id: int, status: str) -> int | None:
        """Applies a proposal's operations (idempotent: overrides once, recompiles that change nothing are no-ops)."""
        p = self.proposals.get(proposal_id)
        ops, plan_id = ops_of(p.ops), p.plan_id
        if not self.overrides.for_proposal(proposal_id):
            for op in ops:
                for o in to_overrides(op):
                    self.overrides.add(plan_id, proposal_id, o.op, o.target, o.payload)
        cause = f"replan:{proposal_id}"
        if any(to_overrides(op) for op in ops):
            for _ in range(3):
                contract, sha = self.plans._contract(plan_id)
                draft = self.plans.compile(contract, self.plans._pinned(plan_id), plan_id)
                try:
                    self.plans.kernel.apply_replan(plan_id, proposal_id, draft, sha)
                    break
                except StaleDraft:
                    continue
        for op in ops:
            if isinstance(op, SwapProgramme):
                self._swap(plan_id, op, cause)
            elif isinstance(op, UpgradePlaybook) and self.plans._pinned(plan_id).version < op.version:
                self.plans.upgrade(plan_id)
            elif isinstance(op, RequestFromStudent):
                self.outbox.add(f"replan:{proposal_id}:{op.instance_key}", "email", self.student_of(plan_id),
                                "replan_request", {"instance_key": op.instance_key, "message": op.message,
                                                   "reason": op.reason})
            elif isinstance(op, Escalate):
                self.support(plan_id, p.event_ids, op.reason, proposal_id)
        with self.engine.connect() as conn:
            revision = conn.execute(select(models.plans.c.current_revision).where(
                models.plans.c.id == plan_id)).scalar_one()
        self.proposals.set_status(proposal_id, status, revision=revision)
        return revision

    def _swap(self, plan_id: int, op: SwapProgramme, cause: str) -> None:
        from app.os.contracts.route_contract import ProgrammeChoice

        def edit(current):
            refs = [x.programme_ref for x in current.programmes]
            if op.out_ref not in refs or op.in_ref in refs:  # already swapped (a repeated step) or overtaken
                raise _AlreadyDone
            return [ProgrammeChoice(programme_ref=op.in_ref if x.programme_ref == op.out_ref else x.programme_ref,
                                    rank=x.rank) for x in current.programmes]

        try:
            self.plans.change_programmes(plan_id, edit, cause)
        except _AlreadyDone:
            pass

    # ------------------------------------------------------------------ the student's answer

    def _own_pending(self, student_ref: str, proposal_id: int):
        p = self.proposals.get(proposal_id)
        if p is None or self.student_of(p.plan_id) != student_ref:
            raise PermissionError("not this student's proposal")
        if p.status != "pending":
            raise ProposalStale(f"this suggestion is already {p.status}")
        if p.expires_at is not None and p.expires_at <= self.clock():
            self.proposals.set_status(p.id, "expired")
            raise ProposalStale("this suggestion has expired")
        return p

    def accept(self, student_ref: str, proposal_id: int) -> int | None:
        """Applies a big proposal the student accepted, after checking it again against the plan as it is now."""
        p = self._own_pending(student_ref, proposal_id)
        ops = ops_of(p.ops)
        kept, refused = self.check(p.plan_id, ops)
        if len(kept) != len(ops):
            raise ProposalStale("your plan changed since this was suggested: " + refused[0]["why"])
        return self.apply(p.id, "accepted")

    def decline(self, student_ref: str, proposal_id: int) -> None:
        p = self._own_pending(student_ref, proposal_id)
        self.proposals.set_status(p.id, "declined")

    def expire_due(self, now: datetime) -> int:
        PR = models.proposals
        with self.engine.connect() as conn:
            ids = conn.execute(select(PR.c.id).where(PR.c.tenant_id == self.tenant, PR.c.status == "pending",
                                                     PR.c.expires_at <= now)).scalars().all()
        for pid in ids:
            self.proposals.set_status(pid, "expired")
        return len(ids)

    def retry(self, plan_id: int, instance_key: str) -> bool:
        """One retry of a failed step through the kernel; False if it is no longer failed."""
        T = models.tasks
        with self.engine.connect() as conn:
            task_id = conn.execute(select(T.c.id).where(T.c.plan_id == plan_id, T.c.instance_key == instance_key)
                                   ).scalar()
        if task_id is None:
            return False
        try:
            self.plans.kernel.retry(task_id)
            return True
        except IllegalTransition:
            return False


class _AlreadyDone(Exception):
    pass


def event_ids(events: list[Event]) -> list[int]:
    return [e.id for e in events]
