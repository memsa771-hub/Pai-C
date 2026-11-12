"""The read-only OS view of one student for the consistency check (P1-T10 A1, master 9.3). Codes, versions, IDs,
hashes and ages only: no fact value, no document text, no file name (R-01). Only SELECTs run here."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import Engine, func, select

from app.os import clock, models
from app.os.adapters.counsellor import intake as intake_mod
from app.os.adapters.counsellor.store import IntakeStore
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.kernel.kernel import contract_sha256
from app.os.kernel.states import PLAN_OPEN
from app.os.ports.plan_source import export_sha256
from app.os.replan import events as replan_events
from app.os.requests import store as request_store

SOURCE = "counsellor"
P, I, EV, V, D = models.plans, models.counsellor_intake, models.events, models.vault_events, models.documents


@dataclass(frozen=True)
class PlanView:
    id: int
    source: str
    status: str  # a plan status
    close_reason: str | None  # the code before ":" in the cause of the revision that closed it
    decision_version: int | None  # the newest decision version this plan applied
    contract_sha256: str
    contract_matches_export: bool | None  # None when no chosen v2 export was given
    export_hash_matches: bool | None  # None when the export is not the version this plan applied


@dataclass(frozen=True)
class FactEventView:
    plan_id: int
    vault_version: int | None
    at: datetime  # tz-aware: when the event was recorded
    age_seconds: float


@dataclass(frozen=True)
class OsSide:
    latest_version: int | None
    intake_status_by_version: Mapping[int, str] = field(default_factory=dict)
    intake_pending_since_by_version: Mapping[int, datetime] = field(default_factory=dict)  # only rows still pending
    refusal_by_version: Mapping[int, str] = field(default_factory=dict)  # a refusal code
    plans: tuple[PlanView, ...] = ()
    latest_vault_version: int | None = None
    unprocessed_fact_events: tuple[FactEventView, ...] = ()
    needed_file_refs: tuple[str, ...] = ()
    duplicate_requests: tuple[tuple[str, str, int], ...] = ()  # (need kind, need ref, count)


def _decision(export: dict | None) -> DecisionRecordV2 | None:
    if not export or export.get("schema") != intake_mod.V2_SCHEMA:
        return None
    try:
        return DecisionRecordV2.model_validate(export)
    except ValidationError:
        return None


def _applied(conn, tenant: str, plan_id: int):
    """The intake row of the newest version this plan applied (None when it has none)."""
    return conn.execute(select(I.c.decision_version, I.c.export_sha256).where(
        I.c.tenant_id == tenant, I.c.plan_id == plan_id, I.c.decision_version.is_not(None))
        .order_by(I.c.decision_version.desc()).limit(1)).first()


def os_side(engine: Engine, tenant: str, student_ref: str, export: dict | None) -> OsSide:
    """What PAI OS holds for the student. `export` is the Counsellor's current export of its newest decision (or None)."""
    now = clock.now()
    decision = _decision(export)
    chosen = decision if decision is not None and decision.status == "chosen" and decision.os_supported else None
    contract_sha = None
    external_ref = None
    if chosen is not None:
        try:
            contract = intake_mod._contract_of(chosen)
            contract_sha, external_ref = contract_sha256(contract), contract.external_ref
        except Exception:  # noqa: BLE001  (an export that cannot be mapped matches nothing)
            contract_sha = external_ref = None
    with engine.connect() as conn:
        rows = conn.execute(select(I.c.decision_version, I.c.status, I.c.reason, I.c.created_at).where(
            I.c.tenant_id == tenant, I.c.student_ref == student_ref, I.c.decision_version.is_not(None))
            .order_by(I.c.decision_version, I.c.id)).all()
        status = {r.decision_version: r.status for r in rows}
        since = {r.decision_version: r.created_at for r in rows if r.status == "pending"}
        refusal = {r.decision_version: r.reason for r in rows if r.status == "refused" and r.reason}
        plans = []
        for p in conn.execute(select(P).where(P.c.tenant_id == tenant, P.c.student_ref == student_ref)
                              .order_by(P.c.id)).all():
            closed = None
            if p.status == "closed":
                cause = conn.execute(select(models.plan_revisions.c.cause).where(
                    models.plan_revisions.c.tenant_id == tenant, models.plan_revisions.c.plan_id == p.id)
                    .order_by(models.plan_revisions.c.number.desc()).limit(1)).scalar()
                closed = cause.split(":")[0] if cause else None
            applied = _applied(conn, tenant, p.id) if p.source == SOURCE else None
            matches = None
            if chosen is not None and p.source == SOURCE and contract_sha is not None:
                matches = p.external_ref == external_ref and p.contract_sha256 == contract_sha
            hash_ok = None
            if applied is not None and decision is not None and applied.decision_version == decision.decision_version:
                hash_ok = applied.export_sha256 == export_sha256(export)
            plans.append(PlanView(p.id, p.source, p.status, closed, applied.decision_version if applied else None,
                                  p.contract_sha256, matches, hash_ok))
        vault = conn.execute(select(func.max(V.c.vault_version)).where(
            V.c.tenant_id == tenant, V.c.student_ref == student_ref)).scalar()
        open_plan = conn.execute(select(P.c.id).where(
            P.c.tenant_id == tenant, P.c.student_ref == student_ref, P.c.status.in_(PLAN_OPEN)).limit(1)).first()
        refs = ()
        if open_plan is not None:
            refs = tuple(conn.execute(select(D.c.file_ref).where(
                D.c.tenant_id == tenant, D.c.student_ref == student_ref, D.c.file_ref.is_not(None),
                D.c.status != "deleted").order_by(D.c.id)).scalars())
    mine = {p.id for p in plans}
    fact_events = []
    for e in replan_events.pending(engine, tenant):
        if e.type == "student_fact_changed" and e.plan_id in mine:
            at = _event_at(engine, tenant, e.id)
            fact_events.append(FactEventView(e.plan_id, e.payload.get("vault_version"), at,
                                             max(0.0, (now - at).total_seconds())))
    dups = tuple((kind, ref, n) for s, kind, ref, n in request_store.duplicates(engine, tenant) if s == student_ref)
    return OsSide(IntakeStore(engine, tenant).latest_version(student_ref), status, since, refusal, tuple(plans), vault,
                  tuple(fact_events), refs, dups)


def _event_at(engine: Engine, tenant: str, event_id: int):
    with engine.connect() as conn:
        return conn.execute(select(EV.c.at).where(EV.c.tenant_id == tenant, EV.c.id == event_id)).scalar_one()


def counsellor_students(engine: Engine, tenant: str) -> list[str]:
    """Students with any Counsellor-source plan or intake row, sorted."""
    with engine.connect() as conn:
        a = select(P.c.student_ref).where(P.c.tenant_id == tenant, P.c.source == SOURCE)
        b = select(I.c.student_ref).where(I.c.tenant_id == tenant)
        return sorted(conn.execute(a.union(b)).scalars())
