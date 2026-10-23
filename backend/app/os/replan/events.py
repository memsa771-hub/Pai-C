"""Replan events (Slice 7 spec S7-D2): a closed list, each recorded once in `os_events` with a dedupe key, and the
detectors that find them. An event is pending until a proposal or a support case names it."""

from dataclasses import dataclass

from sqlalchemy import Connection, Engine, exists, func, insert, select

from app.os import models

EVENT_TYPES = ("admission_rejected", "deadline_at_risk", "document_missing", "task_failed", "playbook_newer",
               "escalate", "approved_changed", "route_invalid")
ADMISSION_TEMPLATE = "admission_result"  # its result {"choice": "rejected"} is a rejection (the Slice 6b inbox)
REVIEW_TEMPLATES = {"review_pack": "pack", "review_visa_file": "visa"}  # review step -> the artifact kind it approves

EV, T, P, PR, C = models.events, models.tasks, models.plans, models.proposals, models.support_cases


@dataclass(frozen=True)
class Event:
    id: int
    plan_id: int
    task_id: int | None
    type: str
    payload: dict


def record(conn: Connection, tenant_id: str, plan_id: int, type_: str, payload: dict, dedupe: str,
           task_id: int | None = None) -> int | None:
    """Records the event unless one of this type with this dedupe key exists for the plan. Returns its id or None."""
    assert type_ in EVENT_TYPES, type_
    seen = conn.execute(select(EV.c.id).where(
        EV.c.tenant_id == tenant_id, EV.c.plan_id == plan_id, EV.c.type == type_,
        EV.c.payload["dedupe"].astext == dedupe)).first()
    if seen is not None:
        return None
    return conn.execute(insert(EV).values(tenant_id=tenant_id, plan_id=plan_id, task_id=task_id, type=type_,
                                          payload={**payload, "dedupe": dedupe}).returning(EV.c.id)).scalar_one()


def pending(engine: Engine, tenant_id: str, plan_id: int | None = None) -> list[Event]:
    """Events of the replan types that no proposal and no support case names yet, oldest first."""
    named = lambda table: exists().where(table.c.tenant_id == tenant_id,  # noqa: E731
                                         table.c.event_ids.contains(func.jsonb_build_array(EV.c.id)))
    q = select(EV).where(EV.c.tenant_id == tenant_id, EV.c.type.in_(EVENT_TYPES), EV.c.plan_id.is_not(None),
                         EV.c.payload.has_key("dedupe"),  # recorded by `record` (Slice 7), not an older log line
                         ~named(PR), ~named(C))
    if plan_id is not None:
        q = q.where(EV.c.plan_id == plan_id)
    with engine.connect() as conn:
        rows = conn.execute(q.order_by(EV.c.id)).all()
    return [Event(r.id, r.plan_id, r.task_id, r.type, r.payload) for r in rows]


def get(engine: Engine, tenant_id: str, event_id: int) -> Event | None:
    with engine.connect() as conn:
        r = conn.execute(select(EV).where(EV.c.tenant_id == tenant_id, EV.c.id == event_id)).first()
    return Event(r.id, r.plan_id, r.task_id, r.type, r.payload) if r else None


def detect_at_risk(engine: Engine, tenant_id: str, plan_id: int) -> int:
    """`deadline_at_risk` for each unfinished critical step with negative slack (after the deadline engine's
    recompile). Returns how many were recorded."""
    with engine.begin() as conn:
        rows = conn.execute(select(T.c.id, T.c.instance_key, T.c.latest_finish, T.c.slack_days).where(
            T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.critical.is_(True), T.c.slack_days < 0,
            T.c.state.not_in(("done", "cancelled", "skipped")))).all()
        found = 0
        for r in rows:
            day = r.latest_finish.date().isoformat() if r.latest_finish else "none"
            found += record(conn, tenant_id, plan_id, "deadline_at_risk",
                            {"instance_key": r.instance_key, "slack_days": r.slack_days},
                            f"{r.instance_key}:{day}", r.id) is not None
    return found


def detect_approved_changed(engine: Engine, tenant_id: str, plan_id: int) -> int:
    """`approved_changed` for each done review step whose approved file has since changed (a new current version
    without that approval): e.g. the visa file's programme was changed after `review_visa_file` was done."""
    from app.os.artifacts.store import ArtifactStore

    with engine.connect() as conn:
        student = conn.execute(select(P.c.student_ref).where(P.c.id == plan_id)).scalar_one()
        reviews = conn.execute(select(T.c.id, T.c.instance_key, T.c.template_key, T.c.programme_ref, T.c.result)
                               .where(T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.state == "done",
                                      T.c.template_key.in_(list(REVIEW_TEMPLATES)))).all()
    arts = ArtifactStore(engine, tenant_id)
    found = 0
    for r in reviews:
        kind = REVIEW_TEMPLATES[r.template_key]
        want = None if kind == "visa" else r.programme_ref
        art = next((a for a in arts.list_for(student) if a.kind == kind and a.programme_ref == want), None)
        approved = (r.result or {}).get("artifacts", {}).get(kind)
        if art is None or not art.current_version or approved is None:
            continue
        if arts.version(art.id, art.current_version).sha256 == approved:
            continue
        with engine.begin() as conn:
            found += record(conn, tenant_id, plan_id, "approved_changed",
                            {"instance_key": r.instance_key.split("#")[0], "template_key": r.template_key,
                             "programme_ref": r.programme_ref, "artifact_id": art.id},
                            f"{art.id}:{art.current_version}", r.id) is not None
    return found
