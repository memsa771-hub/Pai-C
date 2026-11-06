"""The PlanQuery port (Slice 8 spec §2.2, S8-D13, S8-D14): read-only answers for the Counsellor, in process, no
HTTP endpoint. They answer even while the `counsellor` module is off (for tests)."""


from sqlalchemy import select

from app.os import clock, models, ports
from app.os.compiler.compile import needed_fields
from app.os.contracts.plan_summary import PlanSummaryV1
from app.os.contracts.plan_view import PlanViewV1
from app.os.contracts.programme_list import ProgrammeEntry, ProgrammeListV1
from app.os.contracts.route_contract import IntakeRef
from app.os.kernel.states import PLAN_OPEN
from app.os.knowledge.programmes import ProgrammeStore
from app.os.replan.store import OverrideStore
from app.os.plan_view import build_plan_view
from app.os.summary import build_summary


def plan_summary(student_ref: str) -> PlanSummaryV1 | None:
    svc = ports.services()
    return build_summary(svc.engine, svc.settings.tenant_id, student_ref, clock.now())


def plan_view(student_ref: str) -> PlanViewV1:
    """The student's plan as the Counsellor shows it (P1-T5): chosen through the Counsellor intake, `empty` when no
    applied decision maps to a plan."""
    return build_plan_view(ports.services(), student_ref)


def programme_list(route_key: str, intake: IntakeRef) -> ProgrammeListV1:
    """The route's active programmes. `facts_confirmed`: every programme fact the route's newest playbook needs is
    confirmed for that intake year. An unknown route has no programmes."""
    svc = ports.services()
    books = [b for (key, _), b in svc.plans.playbooks.items() if key == route_key]
    if not books:
        return ProgrammeListV1(route_key=route_key, intake=intake, programmes=[])
    _, fields = needed_fields(max(books, key=lambda b: b.version))
    programmes = ProgrammeStore(svc.engine, svc.settings.tenant_id).active(route_key)
    facts = svc.knowledge.programme_facts([p.ref for p in programmes], sorted(fields), intake.year)
    return ProgrammeListV1(route_key=route_key, intake=intake, programmes=[
        ProgrammeEntry(programme_ref=p.ref, university=p.university, name=p.name,
                       facts_confirmed=all((p.ref, f) in facts and facts[(p.ref, f)].confirmed for f in fields))
        for p in programmes])


def routes() -> list[dict]:
    """The routes the loaded playbooks serve (the newest version of each key), for the Counsellor's choice screen:
    `{key, origin, destination, level, intake_terms}`, ordered by key. Raises OsUnavailable when PAI OS is not mounted."""
    newest: dict[str, object] = {}
    for (key, _), book in ports.services().plans.playbooks.items():
        if key not in newest or book.version > newest[key].version:
            newest[key] = book
    return [{"key": k, "origin": b.route.origin, "destination": b.route.destination, "level": b.route.level,
             "intake_terms": list(b.intake_terms)} for k, b in sorted(newest.items())]


def self_serve_plan(student_ref: str) -> dict | None:
    """The student's open self-serve plan (the newest one), for the adoption offer (P1-T6, R-08): `{plan_id, route_key,
    origin, destination, level, intake, programmes, contract_sha256}`, programmes as `{programme_ref, rank}` in order: the live
    places only (the contract's minus those an active `cancel_programme` override dropped), ranked 1..n.
    None when there is none."""
    svc = ports.services()
    P = models.plans
    with svc.engine.connect() as conn:
        row = conn.execute(select(P.c.id, P.c.contract, P.c.contract_sha256).where(
            P.c.tenant_id == svc.settings.tenant_id, P.c.student_ref == student_ref, P.c.source == "self_serve",
            P.c.status.in_(PLAN_OPEN)).order_by(P.c.id.desc()).limit(1)).first()
        if row is None:
            return None
        route_key = conn.execute(select(models.playbook_pins.c.playbook_key).where(
            models.playbook_pins.c.plan_id == row.id)).scalar()
    contract = row.contract
    cancelled = OverrideStore(svc.engine, svc.settings.tenant_id).cancelled(row.id)
    live = [p for p in sorted(contract["programmes"], key=lambda p: p["rank"]) if p["programme_ref"] not in cancelled]
    intake = contract.get("target_intake")
    return {"plan_id": row.id, "route_key": route_key, "origin": contract["origin_country"],
            "destination": contract["destination_country"], "level": contract["level"],
            "intake": None if intake is None else {"term": intake["term"], "year": intake["year"]},
            "programmes": [{"programme_ref": p["programme_ref"], "rank": i + 1} for i, p in enumerate(live)],
            "contract_sha256": row.contract_sha256}
