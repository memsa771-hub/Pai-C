"""The kernel: the only writer of plan state (invariant 1, spec §4.4).

Every public method runs in one transaction that also writes its events and enqueue requests
(the dual-write rule), and holds the plan row lock so concurrent calls on one plan serialise.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import Connection, Engine, and_, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.compiler import CONFIRM_TYPE, DraftTask, PlanDraft
from app.os.contracts.route_contract import RouteContract
from app.os.kernel.revisions import CANCELLED_MARK, DONE_MARK, NOTICE_PREFIX, diff
from app.os.replan import events as replan_events
from app.os.kernel.states import (
    PLAN_CLOSED,
    SATISFIES_DEPENDENCY,
    TERMINAL,
    IllegalTransition,
    TaskState,
    check_transition,
    is_started,
)

P, T, E = models.plans, models.tasks, models.task_edges
S = TaskState
NOTICE_TYPE = "student.act"
REPLAN_CAUSE = "replan:"  # a replan revision's cause: "replan:<proposal id>" (Slice 7)


class StaleDraft(RuntimeError):
    """The draft was compiled from a contract that is no longer the plan's current one: recompile."""


@dataclass(frozen=True)
class PlanRef:
    plan_id: int
    revision: int
    created: bool


@dataclass(frozen=True)
class Outcome:
    status: Literal["done", "failed", "input_missing", "needs_review"]
    result: dict = field(default_factory=dict)
    reason: str | None = None


_OUTCOME_STATE = {
    "done": S.DONE, "failed": S.FAILED, "input_missing": S.WAITING_STUDENT, "needs_review": S.WAITING_REVIEW,
}


def contract_sha256(contract: RouteContract) -> str:
    canonical = json.dumps(contract.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class Kernel:
    def __init__(self, engine: Engine, tenant_id: str, clock: Callable[[], datetime] | None = None) -> None:
        self.engine = engine
        self.tenant_id = tenant_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------------- plans

    def create_plan(self, contract: RouteContract, draft: PlanDraft) -> PlanRef:
        payload = contract.model_dump(mode="json")
        sha = contract_sha256(contract)
        identity = and_(P.c.tenant_id == self.tenant_id, P.c.source == contract.source,
                        P.c.external_ref == contract.external_ref)
        with self.engine.begin() as conn:
            plan_id = conn.execute(
                pg_insert(P).values(
                    tenant_id=self.tenant_id, source=contract.source, external_ref=contract.external_ref,
                    student_ref=contract.student_ref, contract=payload, contract_sha256=sha,
                ).on_conflict_do_nothing(constraint="uq_os_plans_identity").returning(P.c.id)
            ).scalar_one_or_none()
            if plan_id is None:
                row = conn.execute(select(P).where(identity).with_for_update()).one()
                if row.contract_sha256 == sha:
                    return PlanRef(row.id, row.current_revision, False)
                rev = self._revise(conn, row.id, "contract_changed", draft,
                                   contract_update={"contract": payload, "contract_sha256": sha,
                                                    "student_ref": contract.student_ref})
                return PlanRef(row.id, rev or row.current_revision, False)
            conn.execute(insert(models.playbook_pins).values(
                tenant_id=self.tenant_id, plan_id=plan_id, playbook_key=draft.playbook_key,
                version=draft.playbook_version))
            ids = {t.instance_key: self._insert_task(conn, plan_id, t, draft.playbook_version) for t in draft.tasks}
            self._rebuild_edges(conn, plan_id, draft.tasks, ids)
            keys = sorted(ids)
            conn.execute(insert(models.plan_revisions).values(
                tenant_id=self.tenant_id, plan_id=plan_id, number=1, cause="created", diff={"added": keys}))
            self._event(conn, plan_id, None, "plan_created",
                        {"playbook": draft.playbook_key, "version": draft.playbook_version, "tasks": len(keys)})
            self._set_risk(conn, plan_id, draft.at_risk)
            self._promote(conn, plan_id)
            return PlanRef(plan_id, 1, True)

    def revise(self, plan_id: int, cause: str, draft: PlanDraft, based_on: str | None = None) -> int | None:
        """Applies a new draft as a numbered revision. Returns None when nothing structural changed.

        `based_on` is the contract_sha256 the draft was compiled from; if the plan's contract changed
        since, StaleDraft is raised (under the plan lock) and the caller recompiles.
        """
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            self._check_current(conn, plan_id, based_on)
            return self._revise(conn, plan_id, cause, draft)

    def change_contract(self, plan_id: int, contract: RouteContract, draft: PlanDraft, cause: str,
                        based_on: str) -> int | None:
        """Stores a new contract for the plan (e.g. the student swapped a programme, Slice 4) and applies its draft
        as a revision, in one transaction under the plan lock. `based_on` is the contract_sha256 the change was
        made from: if the plan changed since, StaleDraft is raised and the caller starts again from the new one."""
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            self._check_current(conn, plan_id, based_on)
            return self._revise(conn, plan_id, cause, draft, contract_update={
                "contract": contract.model_dump(mode="json"), "contract_sha256": contract_sha256(contract),
                "student_ref": contract.student_ref})

    def upgrade_playbook(self, plan_id: int, draft: PlanDraft, based_on: str | None = None) -> int:
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            self._check_current(conn, plan_id, based_on)
            cause = f"playbook_upgrade:{draft.playbook_key}@{draft.playbook_version}"
            return self._revise(conn, plan_id, cause, draft, pin_version=draft.playbook_version)

    def apply_replan(self, plan_id: int, proposal_id: int, draft: PlanDraft, based_on: str,
                     overrides: Sequence = ()) -> int | None:
        """Applies a replan (Slice 7 S7-D5): the draft compiled with the proposal's overrides, as a numbered revision
        with cause `replan:<proposal id>`, under the plan lock. The overrides (op, target, payload) are stored in the
        same transaction, so a failed revision leaves none behind. StaleDraft if the contract changed since."""
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            self._check_current(conn, plan_id, based_on)
            for o in overrides:
                conn.execute(insert(models.plan_overrides).values(
                    tenant_id=self.tenant_id, plan_id=plan_id, proposal_id=proposal_id, op=o.op, target=o.target,
                    payload=o.payload))
            return self._revise(conn, plan_id, f"{REPLAN_CAUSE}{proposal_id}", draft)

    def close_plan(self, plan_id: int, cause: str) -> int:
        """Closes a plan for good (Slice 8 S8-D8): status `closed`, every open task `cancelled`, one revision with
        `cause` (e.g. `superseded:<new plan id>`). A closed plan is never reopened; closing it again changes nothing
        and returns the revision that closed it."""
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            status, current = conn.execute(select(P.c.status, P.c.current_revision).where(P.c.id == plan_id)).one()
            if status == PLAN_CLOSED:
                return current
            number = current + 1
            cancelled = []
            for row in conn.execute(select(T).where(T.c.plan_id == plan_id, T.c.state.not_in(
                    [s.value for s in TERMINAL])).order_by(T.c.id)).all():
                self._transition(conn, row, S.CANCELLED, cause=cause)
                cancelled.append(row.instance_key)
            conn.execute(insert(models.plan_revisions).values(
                tenant_id=self.tenant_id, plan_id=plan_id, number=number, cause=cause,
                diff={"cancelled": sorted(cancelled)}))
            conn.execute(update(P).where(P.c.id == plan_id).values(
                status=PLAN_CLOSED, current_revision=number, updated_at=self.clock()))
            self._event(conn, plan_id, None, "plan_closed", {"number": number, "cause": cause})
            return number

    def set_changes_paused(self, plan_id: int, paused: bool) -> None:
        """Pauses or resumes replanning for a plan (S7-D9). Student-driven changes are not affected."""
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            conn.execute(update(P).where(P.c.id == plan_id).values(changes_paused=paused, updated_at=self.clock()))
            self._event(conn, plan_id, None, "changes_paused" if paused else "changes_resumed", {})

    def changes_paused(self, plan_id: int) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.execute(select(P.c.changes_paused).where(
                P.c.tenant_id == self.tenant_id, P.c.id == plan_id)).scalar_one())

    def replan_revisions_today(self, plan_id: int) -> int:
        """Replan revisions of this plan since UTC midnight, or since an admin last resumed its changes, whichever is
        later (the daily limit, S7-D9; a resume gives a fresh allowance: final review I10)."""
        now = self.clock().astimezone(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        R, E = models.plan_revisions, models.events
        with self.engine.connect() as conn:
            resumed = conn.execute(select(func.max(E.c.at)).where(
                E.c.tenant_id == self.tenant_id, E.c.plan_id == plan_id, E.c.type == "changes_resumed")).scalar()
            if resumed is not None:
                midnight = max(midnight, resumed)
            return conn.execute(select(func.count()).select_from(R).where(
                R.c.tenant_id == self.tenant_id, R.c.plan_id == plan_id, R.c.cause.like(f"{REPLAN_CAUSE}%"),
                R.c.created_at >= midnight)).scalar_one()

    def _check_current(self, conn: Connection, plan_id: int, based_on: str | None) -> None:
        if based_on is None:
            return
        current = conn.execute(select(P.c.contract_sha256).where(P.c.id == plan_id)).scalar_one()
        if current != based_on:
            raise StaleDraft(f"plan {plan_id} changed since the draft was compiled")

    # ---------------------------------------------------------------- tasks

    def mark_running(self, task_id: int, attempt: int) -> bool:
        with self.engine.begin() as conn:
            row = self._lock_task(conn, task_id)
            if row.attempt != attempt:
                return False
            if row.state == S.RUNNING:
                return True
            if row.state != S.READY:
                return False
            self._transition(conn, row, S.RUNNING, cause="attempt_started")
            conn.execute(pg_insert(models.task_attempts).values(
                tenant_id=self.tenant_id, task_id=task_id, attempt=attempt,
                workflow_id=f"{task_id}:{attempt}", status="running",
            ).on_conflict_do_nothing(constraint="uq_os_task_attempts"))
            return True

    def apply_result(self, task_id: int, attempt: int, outcome: Outcome) -> None:
        with self.engine.begin() as conn:
            row = self._lock_task(conn, task_id)
            if row.attempt != attempt or row.state not in (S.READY, S.RUNNING):
                return  # stale attempt or a repeated result: nothing to do (idempotent)
            if row.state == S.READY:
                row = self._transition(conn, row, S.RUNNING, cause="attempt_started")
            result = dict(outcome.result)
            if outcome.reason:
                result["reason"] = outcome.reason
            self._transition(conn, row, _OUTCOME_STATE[outcome.status], cause=f"result:{outcome.status}",
                             result=result)
            if outcome.status == "failed":  # Slice 7: the replan rules act on it (S7-D2)
                replan_events.record(conn, self.tenant_id, row.plan_id, "task_failed",
                                     {"instance_key": row.instance_key, "reason": outcome.reason, "attempt": attempt},
                                     f"task:{task_id}:{attempt}", task_id)
            done = conn.execute(update(models.task_attempts).where(
                models.task_attempts.c.task_id == task_id, models.task_attempts.c.attempt == attempt,
            ).values(status=outcome.status, ended_at=self.clock()).returning(models.task_attempts.c.id)).first()
            if done is None:
                conn.execute(insert(models.task_attempts).values(
                    tenant_id=self.tenant_id, task_id=task_id, attempt=attempt, workflow_id=f"{task_id}:{attempt}",
                    status=outcome.status, ended_at=self.clock()))
            self._promote(conn, row.plan_id)

    def complete_student_task(self, task_id: int, student_ref: str, payload: dict) -> bool:
        """Marks an inbox item done. A repeat returns False; another student's task raises PermissionError."""
        with self.engine.begin() as conn:
            row = self._lock_task(conn, task_id)
            owner = conn.execute(select(P.c.student_ref).where(P.c.id == row.plan_id)).scalar_one()
            if owner != student_ref or row.kind != "student":
                raise PermissionError("not this student's task")
            if row.state == S.DONE:
                return False
            if row.state != S.WAITING_STUDENT:
                raise IllegalTransition(f"task is {row.state}, not waiting for the student")
            self._transition(conn, row, S.DONE, cause="student_completed", result=payload)
            if row.template_key == replan_events.ADMISSION_TEMPLATE and payload.get("choice") == "rejected":
                replan_events.record(conn, self.tenant_id, row.plan_id, "admission_rejected",
                                     {"programme_ref": row.programme_ref, "instance_key": row.instance_key},
                                     f"task:{task_id}", task_id)
            self._promote(conn, row.plan_id)
            return True

    def complete_review(self, task_id: int, result: dict) -> None:
        with self.engine.begin() as conn:
            row = self._lock_task(conn, task_id)
            if row.state == S.DONE:
                return
            if row.state != S.WAITING_REVIEW:
                raise IllegalTransition(f"task is {row.state}, not waiting for review")
            self._transition(conn, row, S.DONE, cause="review_completed", result=result)
            self._promote(conn, row.plan_id)

    def retry(self, task_id: int) -> int:
        with self.engine.begin() as conn:
            row = self._lock_task(conn, task_id)
            if row.state != S.FAILED:
                raise IllegalTransition(f"only a failed task can be retried (task is {row.state})")
            attempt = row.attempt + 1
            self._transition(conn, row, S.READY, cause="retry", attempt=attempt)
            self._request(conn, task_id, attempt)
            return attempt

    # ---------------------------------------------------------------- internals

    def _event(self, conn: Connection, plan_id: int | None, task_id: int | None, type_: str, payload: dict) -> None:
        conn.execute(insert(models.events).values(
            tenant_id=self.tenant_id, plan_id=plan_id, task_id=task_id, type=type_, payload=payload))

    def _lock_plan(self, conn: Connection, plan_id: int) -> None:
        found = conn.execute(select(P.c.id).where(P.c.id == plan_id, P.c.tenant_id == self.tenant_id)
                             .with_for_update()).first()
        if found is None:
            raise KeyError(f"plan {plan_id}")

    def _lock_task(self, conn: Connection, task_id: int):
        plan_id = conn.execute(select(T.c.plan_id).where(T.c.id == task_id, T.c.tenant_id == self.tenant_id)
                               ).scalar_one_or_none()
        if plan_id is None:
            raise KeyError(f"task {task_id}")
        self._lock_plan(conn, plan_id)
        return conn.execute(select(T).where(T.c.id == task_id)).one()

    def _transition(self, conn: Connection, row, to: TaskState, *, cause: str, **values: Any):
        check_transition(row.state, to)
        new = conn.execute(update(T).where(T.c.id == row.id, T.c.state == row.state).values(
            state=to.value, updated_at=self.clock(), **values).returning(T)).one()
        self._event(conn, row.plan_id, row.id, "task_state", {"from": row.state, "to": to.value, "cause": cause})
        return new

    def _request(self, conn: Connection, task_id: int, attempt: int) -> None:
        conn.execute(pg_insert(models.enqueue_requests).values(
            tenant_id=self.tenant_id, task_id=task_id, attempt=attempt,
        ).on_conflict_do_nothing(constraint="uq_os_enqueue_requests"))

    def _task_values(self, t: DraftTask, version: int) -> dict:
        return {
            "template_key": t.template_key, "task_type": t.task_type, "kind": t.kind, "inbox_kind": t.inbox_kind,
            "programme_ref": t.programme_ref, "title": t.title, "duration_days": t.duration_days,
            "earliest_start": t.earliest_start, "latest_start": t.latest_start, "latest_finish": t.latest_finish,
            "due_at": t.latest_finish, "due_tz": t.due_tz, "provisional": t.provisional, "estimated": t.estimated,
            "blocked_reason": t.blocked_reason, "slack_days": t.slack_days, "critical": t.critical,
            "protected": t.protected, "citations": list(t.citations),
            "fact_refs": [list(f) for f in t.fact_refs], "playbook_version": version,
        }

    def _insert_task(self, conn: Connection, plan_id: int, t: DraftTask, version: int) -> int:
        return conn.execute(insert(T).values(
            tenant_id=self.tenant_id, plan_id=plan_id, instance_key=t.instance_key, state=S.PENDING.value,
            **self._task_values(t, version),
        ).returning(T.c.id)).scalar_one()

    def _rebuild_edges(self, conn: Connection, plan_id: int, tasks, ids: Mapping[str, int]) -> None:
        conn.execute(delete(E).where(E.c.plan_id == plan_id))
        rows = [
            {"tenant_id": self.tenant_id, "plan_id": plan_id, "from_task": ids[dep], "to_task": ids[t.instance_key],
             "hard": hard}
            for t in tasks if t.instance_key in ids for dep, hard in t.depends_on if dep in ids
        ]
        if rows:
            conn.execute(insert(E), rows)

    def _stored_deps(self, conn: Connection, plan_id: int, ids: Mapping[str, int]) -> dict[str, set]:
        key_of = {v: k for k, v in ids.items()}
        deps: dict[str, set] = {}
        for e in conn.execute(select(E).where(E.c.plan_id == plan_id)):
            deps.setdefault(key_of[e.to_task], set()).add((key_of[e.from_task], e.hard))
        return deps

    def _set_risk(self, conn: Connection, plan_id: int, at_risk: bool) -> None:
        status = conn.execute(select(P.c.status).where(P.c.id == plan_id)).scalar_one()
        if status in ("active", "at_risk"):
            conn.execute(update(P).where(P.c.id == plan_id).values(
                status="at_risk" if at_risk else "active", updated_at=self.clock()))
        if at_risk:
            self._event(conn, plan_id, None, "slack_low", {})

    def _revise(self, conn: Connection, plan_id: int, cause: str, draft: PlanDraft, *,
                contract_update: dict | None = None, pin_version: int | None = None) -> int | None:
        stored = {r.instance_key: r._mapping for r in conn.execute(select(T).where(T.c.plan_id == plan_id))}
        ids = {k: r["id"] for k, r in stored.items()}
        new = {t.instance_key: t for t in draft.tasks}
        d = diff(stored, new, self._stored_deps(conn, plan_id, ids), recheck_types=frozenset({CONFIRM_TYPE}))
        if contract_update:
            conn.execute(update(P).where(P.c.id == plan_id).values(**contract_update, updated_at=self.clock()))
        for key, t in new.items():  # drift fields: refreshed in place, never a revision on their own
            if key in stored and not is_started(stored[key]["state"], stored[key]["kind"]):
                conn.execute(update(T).where(T.c.id == ids[key]).values(
                    earliest_start=t.earliest_start, slack_days=t.slack_days, critical=t.critical,
                    citations=list(t.citations), fact_refs=[list(f) for f in t.fact_refs]))
        if d.empty and pin_version is None:
            self._set_risk(conn, plan_id, draft.at_risk)
            return None
        number = conn.execute(select(P.c.current_revision).where(P.c.id == plan_id)).scalar_one() + 1
        for key in d.rechecked:  # the finished check stays as history; its key goes to the fresh task below
            conn.execute(update(T).where(T.c.id == ids.pop(key)).values(instance_key=f"{key}{DONE_MARK}{number}"))
        for key in d.added:
            ids[key] = self._insert_task(conn, plan_id, new[key], draft.playbook_version)
        for key in d.removed:  # unstarted, including open inbox items: all may move to cancelled
            row = conn.execute(select(T).where(T.c.id == ids[key])).one()
            # Renamed so the key is free: if the task comes back later it is a fresh task (review C2).
            self._transition(conn, row, S.CANCELLED, cause=cause,
                             instance_key=f"{key}{CANCELLED_MARK}{number}")
            del ids[key]
        for key, token in d.tokens.items():  # report each started/protected difference only once (C1)
            conn.execute(update(T).where(T.c.id == ids[key]).values(skipped_draft=token))
        for key in d.changed:
            row = conn.execute(select(T).where(T.c.id == ids[key])).one()
            values = self._task_values(new[key], draft.playbook_version)
            conn.execute(update(T).where(T.c.id == row.id).values(**values, updated_at=self.clock()))
            if new[key].blocked_reason and row.state == S.READY:
                row = conn.execute(select(T).where(T.c.id == row.id)).one()
                self._transition(conn, row, S.BLOCKED, cause=cause)
        live = {k: v for k, v in ids.items() if k in new}
        self._rebuild_edges(conn, plan_id, draft.tasks, live)
        conn.execute(insert(models.plan_revisions).values(
            tenant_id=self.tenant_id, plan_id=plan_id, number=number, cause=cause, diff=d.as_json()))
        conn.execute(update(P).where(P.c.id == plan_id).values(current_revision=number, updated_at=self.clock()))
        if pin_version is not None:
            conn.execute(update(models.playbook_pins).where(models.playbook_pins.c.plan_id == plan_id)
                         .values(version=pin_version, pinned_at=self.clock()))
        if not d.empty:
            tz = draft.tasks[0].due_tz if draft.tasks else "UTC"
            conn.execute(insert(T).values(
                tenant_id=self.tenant_id, plan_id=plan_id, instance_key=f"{NOTICE_PREFIX}r{number}",
                template_key="plan_updated", task_type=NOTICE_TYPE, kind="student", inbox_kind="act",
                title="Your plan was updated", state=S.PENDING.value, due_tz=tz,
                playbook_version=draft.playbook_version, result={"revision": number, "cause": cause}))
        self._event(conn, plan_id, None, "plan_revised", {"number": number, "cause": cause, "diff": d.as_json()})
        self._set_risk(conn, plan_id, draft.at_risk)
        self._promote(conn, plan_id)
        return number

    def _promote(self, conn: Connection, plan_id: int) -> None:
        rows = conn.execute(select(T).where(T.c.plan_id == plan_id).order_by(T.c.id)).all()
        state = {r.id: S(r.state) for r in rows}
        hard_preds: dict[int, list[int]] = {}
        for e in conn.execute(select(E).where(E.c.plan_id == plan_id, E.c.hard.is_(True))):
            hard_preds.setdefault(e.to_task, []).append(e.from_task)
        for r in rows:
            st = state[r.id]
            ready = all(state[p] in SATISFIES_DEPENDENCY for p in hard_preds.get(r.id, []))
            if st == S.PENDING and r.blocked_reason:
                self._transition(conn, r, S.BLOCKED, cause="input_missing")
            elif st in (S.PENDING, S.BLOCKED) and not r.blocked_reason and ready:
                attempt = r.attempt + 1 if r.kind == "work" else r.attempt
                row = self._transition(conn, r, S.READY, cause="dependencies_done", attempt=attempt)
                if r.kind == "student":
                    self._transition(conn, row, S.WAITING_STUDENT, cause="inbox")
                else:
                    self._request(conn, r.id, attempt)
        states = conn.execute(select(T.c.state).where(T.c.plan_id == plan_id)).scalars().all()
        if states and all(S(s) in TERMINAL for s in states):
            conn.execute(update(P).where(P.c.id == plan_id, P.c.status != PLAN_CLOSED).values(
                status="done", updated_at=self.clock()))
