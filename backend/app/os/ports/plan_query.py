"""The PlanQuery port (Slice 8 spec §2.2, S8-D13, S8-D14): read-only answers for the Counsellor, in process, no
HTTP endpoint. They answer even while the `counsellor` module is off (for tests)."""


from app.os import clock, ports
from app.os.compiler.compile import needed_fields
from app.os.contracts.plan_summary import PlanSummaryV1
from app.os.contracts.programme_list import ProgrammeEntry, ProgrammeListV1
from app.os.contracts.route_contract import IntakeRef
from app.os.knowledge.programmes import ProgrammeStore
from app.os.summary import build_summary


def plan_summary(student_ref: str) -> PlanSummaryV1 | None:
    svc = ports.services()
    return build_summary(svc.engine, svc.settings.tenant_id, student_ref, clock.now())


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
