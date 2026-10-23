"""Proposals, plan overrides and support cases (Slice 7 spec §3). Every query is filtered by tenant. These tables
are not plan state: the kernel alone writes tasks, edges and revisions (invariant 1); overrides reach the plan only
through a compile and a kernel revision."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, func, insert, select, update

from app.os import models

PR, O, C, P = models.proposals, models.plan_overrides, models.support_cases, models.plans


@dataclass(frozen=True)
class Proposal:
    id: int
    plan_id: int
    event_ids: list[int]
    source: str
    ops: list[dict]
    refused: list[dict]
    big: bool
    status: str
    revision: int | None
    expires_at: datetime | None
    created_at: datetime
    answered_at: datetime | None


@dataclass(frozen=True)
class Override:
    op: str  # skip | cancel | cancel_programme | add | reprioritise
    target: str
    payload: dict


@dataclass(frozen=True)
class SupportCase:
    id: int
    plan_id: int
    student_ref: str
    reason: str
    event_ids: list[int]
    proposal_id: int | None
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


def _proposal(r) -> Proposal:
    return Proposal(r.id, r.plan_id, r.event_ids, r.source, r.ops, r.refused, r.big, r.status, r.revision,
                    r.expires_at, r.created_at, r.answered_at)


def _case(r) -> SupportCase:
    return SupportCase(r.id, r.plan_id, r.student_ref, r.reason, r.event_ids, r.proposal_id, r.status, r.resolution,
                       r.created_at, r.resolved_at)


class ProposalStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def create(self, plan_id: int, event_ids: list[int], source: str, ops: list[dict], refused: list[dict],
               big: bool, expires_at: datetime | None, status: str = "pending") -> int:
        with self.engine.begin() as conn:
            return conn.execute(insert(PR).values(
                tenant_id=self.tenant_id, plan_id=plan_id, event_ids=event_ids, source=source, ops=ops,
                refused=refused, big=big, status=status, expires_at=expires_at).returning(PR.c.id)).scalar_one()

    def get(self, proposal_id: int) -> Proposal | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id)).first()
        return _proposal(row) if row else None

    def for_event(self, event_id: int) -> Proposal | None:
        """The proposal made for this event, if any (one per event: the replan workflow checks it first)."""
        with self.engine.connect() as conn:
            row = conn.execute(select(PR).where(PR.c.tenant_id == self.tenant_id,
                                                PR.c.event_ids.contains([event_id])).order_by(PR.c.id)).first()
        return _proposal(row) if row else None

    def pending_for(self, student_ref: str) -> list[Proposal]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(PR).join(P, P.c.id == PR.c.plan_id).where(
                PR.c.tenant_id == self.tenant_id, P.c.student_ref == student_ref, PR.c.status == "pending")
                .order_by(PR.c.id)).all()
        return [_proposal(r) for r in rows]

    def for_plan(self, plan_id: int) -> list[Proposal]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.plan_id == plan_id)
                                .order_by(PR.c.id.desc())).all()
        return [_proposal(r) for r in rows]

    def set_status(self, proposal_id: int, status: str, revision: int | None = None) -> None:
        values = {"status": status, "revision": revision}
        if status in ("accepted", "declined", "expired"):
            values["answered_at"] = func.now()
        with self.engine.begin() as conn:
            conn.execute(update(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id).values(**values))


class OverrideStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def active(self, plan_id: int | None) -> list[Override]:
        if plan_id is None:
            return []
        with self.engine.connect() as conn:
            rows = conn.execute(select(O.c.op, O.c.target, O.c.payload).where(
                O.c.tenant_id == self.tenant_id, O.c.plan_id == plan_id, O.c.active.is_(True)).order_by(O.c.id)).all()
        return [Override(r.op, r.target, r.payload) for r in rows]

    def add(self, plan_id: int, proposal_id: int, op: str, target: str, payload: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(O).values(tenant_id=self.tenant_id, plan_id=plan_id, proposal_id=proposal_id, op=op,
                                          target=target, payload=payload))

    def for_proposal(self, proposal_id: int) -> list[Override]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(O.c.op, O.c.target, O.c.payload).where(
                O.c.tenant_id == self.tenant_id, O.c.proposal_id == proposal_id).order_by(O.c.id)).all()
        return [Override(r.op, r.target, r.payload) for r in rows]

    def deactivate(self, proposal_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(O).where(O.c.tenant_id == self.tenant_id, O.c.proposal_id == proposal_id)
                         .values(active=False))


class SupportStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def open(self, plan_id: int, student_ref: str, reason: str, event_ids: list[int],
             proposal_id: int | None = None) -> int:
        with self.engine.begin() as conn:
            return conn.execute(insert(C).values(
                tenant_id=self.tenant_id, plan_id=plan_id, student_ref=student_ref, reason=reason,
                event_ids=event_ids, proposal_id=proposal_id).returning(C.c.id)).scalar_one()

    def get(self, case_id: int) -> SupportCase | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(C).where(C.c.tenant_id == self.tenant_id, C.c.id == case_id)).first()
        return _case(row) if row else None

    def list(self, status: str | None = None) -> list[SupportCase]:
        q = select(C).where(C.c.tenant_id == self.tenant_id)
        if status is not None:
            q = q.where(C.c.status == status)
        with self.engine.connect() as conn:
            return [_case(r) for r in conn.execute(q.order_by(C.c.id.desc())).all()]

    def for_event(self, event_id: int) -> SupportCase | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(C).where(C.c.tenant_id == self.tenant_id,
                                               C.c.event_ids.contains([event_id])).order_by(C.c.id)).first()
        return _case(row) if row else None

    def resolve(self, case_id: int, note: str) -> int:
        """Marks the case resolved and returns its plan id (the caller may unpause the plan through the kernel)."""
        with self.engine.begin() as conn:
            return conn.execute(update(C).where(C.c.tenant_id == self.tenant_id, C.c.id == case_id).values(
                status="resolved", resolution=note, resolved_at=func.now()).returning(C.c.plan_id)).scalar_one()
