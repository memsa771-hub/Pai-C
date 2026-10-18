"""The kernel: the only writer of plan state (invariant 1, spec §4.4).

Every public method runs in one transaction that also writes its events and enqueue requests
(the dual-write rule), and holds the plan row lock so concurrent calls on one plan serialise.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import Connection, Engine, and_, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.compiler import DraftTask, PlanDraft
from app.os.contracts.route_contract import RouteContract
from app.os.kernel.revisions import NOTICE_PREFIX, diff
from app.os.kernel.states import (
    SATISFIES_DEPENDENCY,
    TERMINAL,
    UNSTARTED,
    IllegalTransition,
    TaskState,
    check_transition,
)

P, T, E = models.plans, models.tasks, models.task_edges
S = TaskState
NOTICE_TYPE = "student.act"


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

    def revise(self, plan_id: int, cause: str, draft: PlanDraft) -> int | None:
        """Applies a new draft as a numbered revision. Returns None when nothing structural changed."""
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            return self._revise(conn, plan_id, cause, draft)

    def upgrade_playbook(self, plan_id: int, draft: PlanDraft) -> int:
        with self.engine.begin() as conn:
            self._lock_plan(conn, plan_id)
            cause = f"playbook_upgrade:{draft.playbook_key}@{draft.playbook_version}"
            return self._revise(conn, plan_id, cause, draft, pin_version=draft.playbook_version)

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
        d = diff(stored, new, self._stored_deps(conn, plan_id, ids))
        if contract_update:
            conn.execute(update(P).where(P.c.id == plan_id).values(**contract_update, updated_at=self.clock()))
        for key, t in new.items():  # drift fields: refreshed in place, never a revision on their own
            if key in stored and S(stored[key]["state"]) in UNSTARTED:
                conn.execute(update(T).where(T.c.id == ids[key]).values(
                    earliest_start=t.earliest_start, slack_days=t.slack_days, critical=t.critical,
                    citations=list(t.citations), fact_refs=[list(f) for f in t.fact_refs]))
        if d.empty and pin_version is None:
            self._set_risk(conn, plan_id, draft.at_risk)
            return None
        for key in d.added:
            ids[key] = self._insert_task(conn, plan_id, new[key], draft.playbook_version)
        for key in d.removed:
            row = conn.execute(select(T).where(T.c.id == ids[key])).one()
            self._transition(conn, row, S.CANCELLED, cause=cause)
        for key in d.changed:
            row = conn.execute(select(T).where(T.c.id == ids[key])).one()
            values = self._task_values(new[key], draft.playbook_version)
            conn.execute(update(T).where(T.c.id == row.id).values(**values, updated_at=self.clock()))
            if new[key].blocked_reason and row.state == S.READY:
                row = conn.execute(select(T).where(T.c.id == row.id)).one()
                self._transition(conn, row, S.BLOCKED, cause=cause)
        live = {k: v for k, v in ids.items() if k in new}
        self._rebuild_edges(conn, plan_id, draft.tasks, live)
        number = conn.execute(select(P.c.current_revision).where(P.c.id == plan_id)).scalar_one() + 1
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
            conn.execute(update(P).where(P.c.id == plan_id).values(status="done", updated_at=self.clock()))
