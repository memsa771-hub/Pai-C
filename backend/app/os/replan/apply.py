"""Deciding and applying replan proposals (Slice 7 spec S7-D5..D10). Plan state changes only through the kernel
(invariant 1): a proposal's overrides are written in the same transaction as its kernel revision.

One plan's replans and the student's answers run one at a time (a per-plan advisory lock). Every write is keyed by
the proposal, and a proposal by its event, so a repeated step or workflow finds its work already done (invariant 8).
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import TypeAdapter
from sqlalchemy import Engine, func, select, text

from app.os import clock, models
from app.os.adapters.standalone.escalation import StandaloneSink
from app.os.compiler import CompileError
from app.os.kernel import IllegalTransition, StaleDraft
from app.os.ports.escalation import EscalationSink
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
REFUSED_REASON = "Every proposed change was refused by the plan's checks."
BROKEN_REASON = "This plan no longer compiles: a person needs to check it."
LOCK_CLASS = 7007  # pg_advisory_lock(LOCK_CLASS, plan id): one replan or answer per plan at a time
_OPS = TypeAdapter(Ops)


class ProposalStale(ValueError):
    """The proposal can no longer be accepted: answered, expired, or the plan changed so that it no longer fits."""


class ReplanFailed(RuntimeError):
    """The revision could not be written (the plan kept changing, or no longer compiles)."""


@dataclass(frozen=True)
class Decision:
    status: str  # applied | pending | refused | paused | support
    proposal_id: int | None = None


def ops_of(raw: list[dict]) -> list[Op]:
    return list(_OPS.validate_python(raw))


def _writes(op: Op) -> bool:
    """Whether the operation makes a plan revision (and so counts towards the daily limit)."""
    return bool(to_overrides(op)) or isinstance(op, (SwapProgramme, UpgradePlaybook))


class Replanner:
    def __init__(self, engine: Engine, plans, configs: Mapping[str, ReplanConfig], outbox,
                 clock: Callable[[], datetime] = clock.now, escalations: EscalationSink | None = None) -> None:
        self.engine, self.plans, self.configs, self.outbox, self.clock = engine, plans, configs, outbox, clock
        self.tenant = plans.kernel.tenant_id
        self.proposals, self.overrides = ProposalStore(engine, self.tenant), OverrideStore(engine, self.tenant)
        self.support_cases = SupportStore(engine, self.tenant)
        # every support case goes through the port (Slice 8 S8-D12); standalone only unless the caller wires more
        self.escalations = escalations or StandaloneSink(engine, self.tenant, self.student_of)

    @contextmanager
    def plan_lock(self, plan_id: int) -> Iterator[None]:
        """Holds the plan's replan lock (a session advisory lock) for the block (final review I2, I5)."""
        with self.engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:c, :p)"), {"c": LOCK_CLASS, "p": plan_id})
            conn.commit()
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:c, :p)"), {"c": LOCK_CLASS, "p": plan_id})
                conn.commit()

    # ------------------------------------------------------------------ state

    def config(self, plan_id: int) -> ReplanConfig:
        return self.configs.get(self.plans._pinned(plan_id).key, ReplanConfig())

    def student_of(self, plan_id: int) -> str:
        with self.engine.connect() as conn:
            return conn.execute(select(models.plans.c.student_ref).where(models.plans.c.id == plan_id)).scalar_one()

    def _base(self, plan_id: int) -> tuple[str, int]:
        with self.engine.connect() as conn:
            row = conn.execute(select(models.plans.c.contract_sha256, models.plans.c.current_revision).where(
                models.plans.c.id == plan_id)).one()
        return row.contract_sha256, row.current_revision

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
        """(kept, refused). Raises CompileError when the plan does not compile even without the operations."""
        contract, _ = self.plans._contract(plan_id)
        book = self.plans._pinned(plan_id)

        def compile_with(candidate: list[Op]):
            return self.plans.compile(contract, book, plan_id, [o for op in candidate for o in to_overrides(op)])

        year = contract.target_intake.year
        upgrades = [op for op in ops if isinstance(op, UpgradePlaybook)
                    and (book.key, op.version) not in self.plans.playbooks]
        refused = [{"op": op.model_dump(mode="json"), "why": f"version {op.version} of the guide does not exist"}
                   for op in upgrades]
        rest = [op for op in ops if op not in upgrades]
        kept, more = check_operations(rest, task_rows(self.engine, self.tenant, plan_id), book, compile_with,
                                      compile_with([]), lambda ref: self.confirmed(ref, year))
        return kept, refused + more

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
        with self.plan_lock(plan_id):
            return self._decide(plan_id, event_ids, source, ops)

    def _finish(self, existing, plan_id: int, event_ids: list[int]) -> Decision:
        """A repeated step: complete whatever the first run left undone (final review I6)."""
        if existing.status == "applied" and existing.revision is None and existing.ops:
            try:
                self.apply(existing.id, "applied")
            except ReplanFailed as e:
                self.support(plan_id, event_ids, str(e), existing.id)
                return Decision("support", existing.id)
        elif existing.status == "refused":
            limit = any(r.get("limit") for r in existing.refused)
            broken = any(r.get("broken") for r in existing.refused)
            if limit and not self.plans.kernel.changes_paused(plan_id):
                self.plans.kernel.set_changes_paused(plan_id, True)
            self.support(plan_id, event_ids, LIMIT_REASON if limit else BROKEN_REASON if broken else REFUSED_REASON,
                         existing.id)
            return Decision("paused" if limit else "refused", existing.id)
        return Decision(existing.status, existing.id)

    def _refuse(self, plan_id: int, event_ids: list[int], source: str, raw: list[dict], refused: list[dict],
                marker: dict | None = None) -> int:
        return self.proposals.create(plan_id, event_ids, source, raw, [*refused, *([marker] if marker else [])],
                                     big=False, expires_at=None, status="refused")

    def _decide(self, plan_id: int, event_ids: list[int], source: str, ops: list[Op]) -> Decision:
        existing = self.proposals.for_event(event_ids[0])
        if existing is not None:
            return self._finish(existing, plan_id, event_ids)
        if self.plans.kernel.changes_paused(plan_id):
            return Decision("paused")
        try:
            kept, refused = self.check(plan_id, ops)
        except CompileError as e:  # the plan itself no longer compiles (final review C1)
            pid = self._refuse(plan_id, event_ids, source, [], [], {"why": str(e)[:200], "broken": True})
            self.support(plan_id, event_ids, BROKEN_REASON, pid)
            return Decision("support", pid)
        kept = kept[:10]
        if ops and not kept:
            pid = self._refuse(plan_id, event_ids, source, [], refused)
            self.support(plan_id, event_ids, REFUSED_REASON, pid)
            return Decision("refused", pid)
        tasks = task_rows(self.engine, self.tenant, plan_id)
        book = self.plans._pinned(plan_id)
        raw = [op.model_dump(mode="json") for op in kept]
        sha, revision = self._base(plan_id)
        if any(is_big(op, tasks, book) for op in kept):
            pid = self.proposals.create(plan_id, event_ids, source, raw, refused, big=True,
                                        expires_at=self._expires(plan_id, kept), based_on=sha, base_revision=revision)
            return Decision("pending", pid)
        if any(_writes(op) for op in kept) and self.plans.kernel.replan_revisions_today(plan_id) >= DAILY_REVISIONS:
            pid = self._refuse(plan_id, event_ids, source, raw, refused, {"why": LIMIT_REASON, "limit": True})
            self.plans.kernel.set_changes_paused(plan_id, True)
            self.support(plan_id, event_ids, LIMIT_REASON, pid)
            return Decision("paused", pid)
        pid = self.proposals.create(plan_id, event_ids, source, raw, refused, big=False, expires_at=None,
                                    status="applied", based_on=sha, base_revision=revision)
        if kept:
            try:
                self.apply(pid, "applied")
            except ReplanFailed as e:
                self.support(plan_id, event_ids, str(e), pid)
                return Decision("support", pid)
        return Decision("applied", pid)

    def close(self, plan_id: int, event_ids: list[int]) -> int:
        """Marks events handled with nothing to change (an empty, applied proposal)."""
        existing = self.proposals.for_event(event_ids[0])
        if existing is not None:
            return existing.id
        return self.proposals.create(plan_id, event_ids, "rules", [], [], big=False, expires_at=None, status="applied")

    def support(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        return self.escalations.escalate(plan_id, event_ids, reason, proposal_id)

    # ------------------------------------------------------------------ applying

    def apply(self, proposal_id: int, status: str) -> int | None:
        """Applies a proposal's operations. The overrides and the revision are one kernel transaction (final review
        I3); a repeat finds them stored and recompiles to no change. Raises ReplanFailed if it cannot be written."""
        p = self.proposals.get(proposal_id)
        ops, plan_id = ops_of(p.ops), p.plan_id
        stored = bool(self.overrides.for_proposal(proposal_id))
        new = [] if stored else [o for op in ops for o in to_overrides(op)]
        cause = f"replan:{proposal_id}"
        if any(to_overrides(op) for op in ops):
            for _ in range(3):
                contract, sha = self.plans._contract(plan_id)
                try:
                    draft = self.plans.compile(contract, self.plans._pinned(plan_id), plan_id, new)
                    self.plans.kernel.apply_replan(plan_id, proposal_id, draft, sha, overrides=new)
                    break
                except StaleDraft:
                    continue
                except CompileError as e:
                    raise ReplanFailed(f"{BROKEN_REASON} ({e})"[:300]) from None
            else:
                raise ReplanFailed("The plan kept changing while this change was being made.")
        for op in ops:
            if isinstance(op, SwapProgramme):
                self._swap(plan_id, op, cause)
            elif isinstance(op, UpgradePlaybook) and self.plans._pinned(plan_id).version < op.version:
                self.plans.upgrade(plan_id, op.version)
            elif isinstance(op, RequestFromStudent):  # one nudge per step per day (final review I2)
                day = self.clock().astimezone(timezone.utc).date().isoformat()
                self.outbox.add(f"replan:{plan_id}:{op.instance_key}:{day}", "email", self.student_of(plan_id),
                                "replan_request", {"instance_key": op.instance_key, "message": op.message,
                                                   "reason": op.reason})
            elif isinstance(op, Escalate):
                self.support(plan_id, p.event_ids, op.reason, proposal_id)
        revision = self._base(plan_id)[1]
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
        """Applies a big proposal the student accepted, after checking it again against the plan as it is now: a
        changed contract (a swap, a reorder) or an operation that no longer fits refuses it (final review I4)."""
        p = self.proposals.get(proposal_id)
        if p is None:
            raise PermissionError("not this student's proposal")
        with self.plan_lock(p.plan_id):
            p = self._own_pending(student_ref, proposal_id)
            if p.based_on is not None and self._base(p.plan_id)[0] != p.based_on:
                raise ProposalStale("your plan changed since this was suggested")
            ops = ops_of(p.ops)
            try:
                kept, refused = self.check(p.plan_id, ops)
            except CompileError:
                raise ProposalStale("your plan changed since this was suggested") from None
            if len(kept) != len(ops):
                raise ProposalStale("your plan changed since this was suggested: " + refused[0]["why"])
            try:
                return self.apply(p.id, "accepted")
            except ReplanFailed as e:
                raise ProposalStale(f"your plan changed since this was suggested ({e})") from None

    def decline(self, student_ref: str, proposal_id: int) -> None:
        p = self.proposals.get(proposal_id)
        if p is None:
            raise PermissionError("not this student's proposal")
        with self.plan_lock(p.plan_id):
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
