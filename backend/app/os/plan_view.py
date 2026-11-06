"""PlanView v1 (P1-T5 Task 1, R-04, R-44): what PAI OS shows the Counsellor of one student's plan, built on every read
from the plan tables, never stored, read-only. Plan selection goes through the Counsellor intake (D-s): the OS plan is
the one the student's newest decision maps to, never merely the student's newest plan (a self-serve plan, or one the
newest decision has not reached yet, is not shown)."""

import re
from typing import Any

from sqlalchemy import Connection, func, select

from app.os import models
from app.os.contracts.plan_view import (ConsentState, DocumentNeed, PlanChange, PlanRoute, PlanStep, PlanViewV1)
from app.os.kernel.revisions import CANCELLED_MARK, DONE_MARK, NOTICE_PREFIX
from app.os.kernel.states import PLAN_CLOSED
from app.os.playbooks.loader import PlaybookError, select_playbook
from app.os.ports import document_files

D = models.documents
P, T, E, R, PR, EV, I, PIN = (models.plans, models.tasks, models.task_edges, models.plan_revisions, models.proposals,
                              models.events, models.counsellor_intake, models.playbook_pins)
_CODE = re.compile(r"^[a-z_]+$")
_PLAN_STATUSES = ("planned", "revised", "replaced", "paused")  # the intake outcomes that point at a live plan
_CLOSED_STATUSES = ("withdrawn", "unsupported")  # the plan was closed by the decision
_APPLIED = _PLAN_STATUSES + _CLOSED_STATUSES
_DIFF_KIND = (("added", "added"), ("removed", "removed"), ("changed", "revised"))


def _code(text: str | None, default: str | None = None) -> str | None:
    """A code from a stored cause or reason: the part before ":" when it is one, else `default`."""
    head = (text or "").split(":", 1)[0]
    return head if _CODE.match(head) else default


def _hidden(key: str) -> bool:
    return key.startswith(NOTICE_PREFIX) or CANCELLED_MARK in key or DONE_MARK in key


def _empty(student_ref: str) -> PlanViewV1:
    return PlanViewV1(student_ref=student_ref, state="empty", state_reason=None, plan_id=None, decision_version=None,
                      revision=None, route=None, pages=[], consent=None, steps=[], requests=[], documents_needed=[],
                      changes=[], proposals_waiting=0)


def _newest_decision(conn: Connection, tenant_id: str, student_ref: str):
    """The student's newest APPLIED decision that has a plan (highest version; v1 rows, which have none, rank lowest).
    A newer decision still pending, held, refused or stale does not hide it: its version tells the adapter the lag."""
    return conn.execute(select(I).where(I.c.tenant_id == tenant_id, I.c.student_ref == student_ref,
                                        I.c.status.in_(_APPLIED), I.c.plan_id.is_not(None))
                        .order_by(I.c.decision_version.desc().nulls_last(), I.c.id.desc()).limit(1)).first()


def _consent(export: dict) -> ConsentState:
    if export.get("guardian_required"):
        guardian = "given" if export.get("guardian_authorized_at") else "missing"
    else:
        guardian = "not_needed"
    return ConsentState(student="given" if export.get("authorized_at") else "missing", guardian=guardian)


def _steps(conn: Connection, tenant_id: str, plan_id: int) -> list[PlanStep]:
    rows = [t for t in conn.execute(select(T).where(T.c.tenant_id == tenant_id, T.c.plan_id == plan_id)
                                    .order_by(T.c.id)).all() if not _hidden(t.instance_key)]
    key_of = {t.id: t.instance_key for t in rows}
    deps: dict[int, list[str]] = {}
    for e in conn.execute(select(E).where(E.c.tenant_id == tenant_id, E.c.plan_id == plan_id).order_by(E.c.id)):
        if e.from_task in key_of and e.to_task in key_of:
            deps.setdefault(e.to_task, []).append(key_of[e.from_task])
    return [PlanStep(
        task_id=t.id, instance_key=t.instance_key, template_key=t.template_key, title=t.title,
        owner="student" if t.kind == "student" else "pai", status=t.state,
        blocked_reason=_code(t.blocked_reason, "blocked") if t.blocked_reason else None,
        inbox_kind=t.inbox_kind, programme_ref=t.programme_ref, due_at=t.due_at, due_tz=t.due_tz if t.due_at else None,
        depends_on=deps.get(t.id, []), provisional=t.provisional, estimated=t.estimated, needs=[]) for t in rows]


def _changes(conn: Connection, tenant_id: str, plan_id: int) -> list[PlanChange]:
    out = []
    for r in conn.execute(select(R).where(R.c.tenant_id == tenant_id, R.c.plan_id == plan_id, R.c.number >= 2)
                          .order_by(R.c.number)).all():
        cause = _code(r.cause, "other")
        for name, kind in _DIFF_KIND:
            for key in (r.diff or {}).get(name) or []:
                if not _hidden(key):
                    out.append(PlanChange(revision=r.number, at=r.created_at, cause=cause, kind=kind, instance_key=key))
    return out


_UPLOADED = ("uploaded", "reading", "read", "needs_student")  # a file is there and the student has not confirmed it


def _documents_needed(svc: Any, student_ref: str, route_key: str) -> list[DocumentNeed]:
    """The documents of the route's pack checklist, each missing, uploaded or confirmed (P1-T7, D-y14, R-16). Only
    while the one upload is on; a route with no pack config, or a service without any, gives none."""
    if not document_files.enabled():
        return []
    # route_key is the playbook key, which is also the pack-config key
    cfg = (getattr(svc, "pack_configs", None) or {}).get(route_key)
    if cfg is None:
        return []
    have: dict[str, str] = {}
    with svc.engine.connect() as conn:
        rows = conn.execute(select(D.c.doc_type, D.c.status).where(
            D.c.tenant_id == svc.settings.tenant_id, D.c.student_ref == student_ref, D.c.status != "deleted")).all()
    for doc_type, status in rows:
        if status == "confirmed" or (status in _UPLOADED and have.get(doc_type) != "confirmed"):
            have[doc_type] = "confirmed" if status == "confirmed" else "uploaded"
    refs = list(dict.fromkeys(i.ref for i in cfg.checklist if i.kind == "document"))
    return [DocumentNeed(doc_type=ref, status=have.get(ref, "missing")) for ref in refs]


def build_plan_view(svc: Any, student_ref: str) -> PlanViewV1:
    tenant_id = svc.settings.tenant_id
    with svc.engine.connect() as conn:
        decision = _newest_decision(conn, tenant_id, student_ref)
        if decision is None:
            return _empty(student_ref)
        plan = conn.execute(select(P).where(P.c.tenant_id == tenant_id, P.c.id == decision.plan_id)).first()
        if plan is None:
            return _empty(student_ref)
        steps = _steps(conn, tenant_id, plan.id)
        waiting = conn.execute(select(func.count()).select_from(PR).where(
            PR.c.tenant_id == tenant_id, PR.c.plan_id == plan.id, PR.c.status == "pending")).scalar()
        version = decision.decision_version
        pin = conn.execute(select(PIN.c.playbook_key, PIN.c.version).where(
            PIN.c.tenant_id == tenant_id, PIN.c.plan_id == plan.id)
            .order_by(PIN.c.version.desc(), PIN.c.id.desc()).limit(1)).first()
        reason = None
        if plan.status == PLAN_CLOSED:
            cause = conn.execute(select(R.c.cause).where(
                R.c.tenant_id == tenant_id, R.c.plan_id == plan.id, R.c.number == plan.current_revision)).scalar()
            reason = _code(cause)
        elif plan.status == "paused" and decision.status not in _CLOSED_STATUSES:  # a stop is not a pause
            payload = conn.execute(select(EV.c.payload).where(
                EV.c.tenant_id == tenant_id, EV.c.plan_id == plan.id, EV.c.type == "plan_paused")
                .order_by(EV.c.id.desc()).limit(1)).scalar()
            reason = _code((payload or {}).get("reason"))
        changes = _changes(conn, tenant_id, plan.id)
    if plan.status == "done":
        state = "finished"
    elif plan.status == PLAN_CLOSED or decision.status in _CLOSED_STATUSES:
        state = "stopped"  # the decision stopped it, even if the close has not reached the plan yet
        reason = reason or decision.status
    elif plan.status == "paused":
        state = "paused"
    elif waiting or any(s.owner == "student" and s.status == "waiting_student" for s in steps):
        state = "needs_student"
    else:
        state = "active"
    c = plan.contract
    try:
        origin, destination, level, intake = (c["origin_country"], c["destination_country"], c["level"],
                                              c["target_intake"])
    except (KeyError, TypeError) as e:
        raise ValueError(f"plan {plan.id} has a contract without its route") from e
    if pin is None:  # no pin: the playbook this route runs on (legacy: pins are written at compile, so this takes the newest version)
        try:
            book = select_playbook(svc.plans.playbooks, origin, destination, level)
        except PlaybookError as e:
            raise ValueError(f"plan {plan.id} has no playbook pin and no playbook serves its route") from e
        route_key, book_key = book.key, (book.key, book.version)
    else:
        route_key, book_key = pin.playbook_key, (pin.playbook_key, pin.version)
    pages = [p.key for p in (getattr(svc.plans.playbooks.get(book_key), "pages", None) or [])]  # D-z6
    # consent is the applied row's: the Counsellor holds the newest consent itself and shows it from its own side
    return PlanViewV1(
        student_ref=student_ref, state=state, state_reason=reason, plan_id=plan.id, decision_version=version,
        revision=plan.current_revision,
        route=PlanRoute(route_key=route_key, origin_country=origin, destination_country=destination, level=level,
                        target_intake=intake),
        pages=pages, consent=_consent(decision.export or {}), steps=steps, requests=[],
        documents_needed=_documents_needed(svc, student_ref, route_key), changes=changes, proposals_waiting=waiting)
