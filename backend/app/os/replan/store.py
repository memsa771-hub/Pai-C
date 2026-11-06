"""Proposals, plan overrides and support cases (Slice 7 spec §3). Every query is filtered by tenant. These tables
are not plan state: the kernel alone writes tasks, edges and revisions (invariant 1); overrides reach the plan only
through a compile and a kernel revision."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, Engine, and_, func, insert, or_, select, update

from app.os import clock, models
from app.os.kernel.states import PLAN_OPEN
from app.os.ports import os_events

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
    based_on: str | None = None  # the plan's contract SHA-256 and revision when proposed
    base_revision: int | None = None
    base_decision_version: int | None = None  # P1-T6: the decision version it was made against; None before os_0021
    requested_version: int | None = None  # the version n+1 the Counsellor wrote for the request
    request_outcome: str | None = None  # written | duplicate | stale | refused


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
    counsellor_status: str | None = None  # Slice 8: pending | sent | refused, for a route problem told the Counsellor
    counsellor_reason: str | None = None


def _proposal(r) -> Proposal:
    return Proposal(r.id, r.plan_id, r.event_ids, r.source, r.ops, r.refused, r.big, r.status, r.revision,
                    r.expires_at, r.created_at, r.answered_at, r.based_on, r.base_revision, r.base_decision_version,
                    r.requested_version, r.request_outcome)


def _case(r) -> SupportCase:
    return SupportCase(r.id, r.plan_id, r.student_ref, r.reason, r.event_ids, r.proposal_id, r.status, r.resolution,
                       r.created_at, r.resolved_at, r.counsellor_status, r.counsellor_reason)


class ProposalStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def create(self, plan_id: int, event_ids: list[int], source: str, ops: list[dict], refused: list[dict],
               big: bool, expires_at: datetime | None, status: str = "pending", based_on: str | None = None,
               base_revision: int | None = None, base_decision_version: int | None = None,
               conn: Connection | None = None) -> int:
        """Inserts the proposal. With `conn` it joins the caller's transaction (the builder's request is one: the
        proposal and its choice_request row commit together); otherwise it is its own."""
        if conn is None:
            with self.engine.begin() as own:
                return self.create(plan_id, event_ids, source, ops, refused, big, expires_at, status, based_on,
                                   base_revision, base_decision_version, conn=own)
        proposal_id = conn.execute(insert(PR).values(
            tenant_id=self.tenant_id, plan_id=plan_id, event_ids=event_ids, source=source, ops=ops,
            refused=refused, big=big, status=status, expires_at=expires_at, based_on=based_on,
            base_revision=base_revision, base_decision_version=base_decision_version).returning(PR.c.id)
        ).scalar_one()
        if status == "pending":  # a suggestion waits for the student: tell the Counsellor in this transaction
            os_events.emit(conn, self.tenant_id, plan_id, "proposal_waiting", proposal_id, clock.now())
        return proposal_id

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

    def requested_for(self, student_ref: str, since: datetime) -> list[Proposal]:
        """The student's choice changes that went to the Counsellor: those still `requested` on an open plan, and
        those that ended `expired` with the Counsellor's answer since `since` (P1-T6)."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(PR).join(P, P.c.id == PR.c.plan_id).where(
                PR.c.tenant_id == self.tenant_id, P.c.student_ref == student_ref,
                or_(and_(PR.c.status == "requested", P.c.status.in_(PLAN_OPEN)),
                    and_(PR.c.status == "expired", PR.c.request_outcome.is_not(None), PR.c.answered_at >= since))
            ).order_by(PR.c.id)).all()
        return [_proposal(r) for r in rows]

    def pending_for(self, student_ref: str) -> list[Proposal]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(PR).join(P, P.c.id == PR.c.plan_id).where(
                PR.c.tenant_id == self.tenant_id, P.c.student_ref == student_ref, PR.c.status == "pending",
                P.c.status.in_(PLAN_OPEN)).order_by(PR.c.id)).all()  # never a closed plan's (final review I2)
        return [_proposal(r) for r in rows]

    def for_plan(self, plan_id: int) -> list[Proposal]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.plan_id == plan_id)
                                .order_by(PR.c.id.desc())).all()
        return [_proposal(r) for r in rows]

    def set_status(self, proposal_id: int, status: str, revision: int | None = None) -> None:
        values = {"status": status, "revision": revision}
        if status in ("accepted", "declined", "expired", "requested"):
            values["answered_at"] = func.now()
        with self.engine.begin() as conn:
            conn.execute(update(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id).values(**values))

    def expire_if_pending(self, proposal_id: int) -> bool:
        """Expires the proposal only while it is still pending; an answered one is left as it is. True if it changed."""
        with self.engine.begin() as conn:
            done = conn.execute(update(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id,
                                                 PR.c.status == "pending").values(status="expired",
                                                                                  answered_at=func.now()))
        return done.rowcount == 1

    def request(self, conn: Connection, proposal_id: int, revision: int | None) -> bool:
        """pending → requested on the CALLER's connection, so the status and the choice_request row it goes with
        commit together or not at all (R-07). `revision` is the one the other ops of the proposal made, if any.
        True if it changed."""
        # answered_at on a `requested` row is the time the student answered (accepted), not when the Counsellor did
        done = conn.execute(update(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id,
                                             PR.c.status == "pending")
                            .values(status="requested", revision=revision, answered_at=func.now()))
        return done.rowcount == 1

    def settle_requested(self, plan_id: int, applied_version: int, revision: int | None,
                         conn: Connection | None = None) -> int:
        """requested → accepted for this plan's requests whose version is now applied (D-x3). Idempotent: only a
        `requested` row moves, so a second call changes nothing. Keeps an earlier revision when `revision` is None.
        Returns how many proposals moved."""
        q = update(PR).where(
            PR.c.tenant_id == self.tenant_id, PR.c.plan_id == plan_id, PR.c.status == "requested",
            PR.c.requested_version.is_not(None), PR.c.requested_version <= applied_version
        ).values(status="accepted", revision=func.coalesce(revision, PR.c.revision), answered_at=func.now())
        if conn is not None:
            return conn.execute(q).rowcount
        with self.engine.begin() as own:
            return own.execute(q).rowcount

    def expire_requested(self, proposal_id: int, outcome: str) -> bool:
        """requested → expired, recording the Counsellor's answer (`stale`, `refused`) or the reason it ended.
        True if it changed."""
        with self.engine.begin() as conn:
            done = conn.execute(update(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id,
                                                 PR.c.status == "requested")
                                .values(status="expired", request_outcome=outcome, answered_at=func.now()))
        return done.rowcount == 1

    def set_requested_version(self, proposal_id: int, version: int, outcome: str) -> bool:
        """The Counsellor wrote (or already had) `version` for this request: `written` or `duplicate`. The proposal
        stays `requested` until the OS applies that version. True if it changed."""
        if outcome not in ("written", "duplicate"):
            raise ValueError(f"{outcome!r} does not write a version: stale and refused expire the proposal")
        with self.engine.begin() as conn:
            done = conn.execute(update(PR).where(PR.c.tenant_id == self.tenant_id, PR.c.id == proposal_id,
                                                 PR.c.status == "requested")
                                .values(requested_version=version, request_outcome=outcome))
        return done.rowcount == 1


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

    def cancelled(self, plan_id: int) -> set[str]:
        """The programmes an active override has dropped from the plan (the contract still lists them)."""
        return {o.target for o in self.active(plan_id) if o.op == "cancel_programme"}

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
