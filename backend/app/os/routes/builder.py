"""The self-serve route builder (Slice 4 spec S4-D9, S4-D10, Q3): a student starts and changes their own plan.

Plans start and change only through PlanService and the kernel (invariant 1). Nothing here is route-specific: the
route's origin, destination and level come from its playbook, and the task the builder completes is named there
(`self_serve.choose_task`). Eligibility never blocks a choice (S4-D5); these checks are about the plan itself.
"""

from pydantic import ValidationError
from sqlalchemy import func, select, text

from app.os import models
from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice, RouteContract
from app.os.kernel import PlanRef
from app.os.kernel.states import is_started
from app.os.knowledge.requests import visible_programmes

CHANGES_PER_DAY = 3  # swaps and removals per plan (S4-D10); the kernel has no revision limit yet (Slice 7)
P, T, R, F = models.plans, models.tasks, models.plan_revisions, models.knowledge_facts


class NotAllowed(ValueError):
    """The change cannot be made; the message is safe to show the student."""


class SwapLimit(NotAllowed):
    """CHANGES_PER_DAY programme changes in the last 24 hours."""


def _route(plans, route_key: str):
    books = [b for (key, _), b in plans.playbooks.items() if key == route_key]
    if not books:
        raise NotAllowed(f"unknown route '{route_key}'")
    return max(books, key=lambda b: b.version)


def _check_programmes(plans, route_key: str, year: int, refs: list[str]) -> None:
    visible = {p.ref for p in visible_programmes(plans.engine, plans.kernel.tenant_id, route_key, year)}
    unknown = [r for r in refs if r not in visible]
    if unknown:
        raise NotAllowed(f"not a programme of this route for {year}: {', '.join(unknown)}")


def start(plans, student_ref: str, route_key: str, intake: IntakeRef, choices: list[ProgrammeChoice]) -> PlanRef:
    """Starts the student's plan for a route and intake (or returns the one they already have)."""
    book = _route(plans, route_key)
    if len(choices) > 10:
        raise NotAllowed("choose at most 10 programmes")
    _check_programmes(plans, route_key, intake.year, [c.programme_ref for c in choices])
    try:
        contract = RouteContract.model_validate({
            "contract_version": "1", "source": "self_serve",
            "external_ref": f"self:{student_ref}:{route_key}:{intake.term}:{intake.year}",
            "student_ref": student_ref, "origin_country": book.route.origin,
            "destination_country": book.route.destination, "level": book.route.level,
            "target_intake": intake.model_dump(), "programmes": [c.model_dump() for c in choices]})
    except ValidationError as e:
        raise NotAllowed(e.errors()[0]["msg"]) from None
    ref = plans.start_plan(contract)
    task = book.self_serve.choose_task if book.self_serve else None
    if task and ref.created:
        with plans.engine.connect() as conn:
            row = conn.execute(select(T.c.id, T.c.state).where(T.c.plan_id == ref.plan_id,
                                                               T.c.instance_key == task)).first()
        if row is not None and row.state == "waiting_student":
            plans.kernel.complete_student_task(row.id, student_ref, {"programmes": [c.programme_ref for c in choices]})
    return ref


def _own(plans, student_ref: str, plan_id: int) -> RouteContract:
    with plans.engine.connect() as conn:
        owner = conn.execute(select(P.c.student_ref).where(
            P.c.id == plan_id, P.c.tenant_id == plans.kernel.tenant_id)).scalar_one_or_none()
    if owner != student_ref:
        raise NotAllowed("this plan is not yours")
    return plans._contract(plan_id)[0]


def _not_started(plans, plan_id: int, ref: str) -> None:
    with plans.engine.connect() as conn:
        rows = conn.execute(select(T.c.title, T.c.state, T.c.kind, T.c.protected).where(
            T.c.plan_id == plan_id, T.c.programme_ref == ref)).all()
    for r in rows:
        if r.state != "cancelled" and (is_started(r.state, r.kind) or r.protected):
            raise NotAllowed(f"work on {ref} has started ({r.title}), so it cannot be changed")


def _within_limit(plans, plan_id: int) -> None:
    """Counted on the database's clock, the one that stamps each revision."""
    with plans.engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(R).where(
            R.c.plan_id == plan_id, R.c.created_at > func.now() - text("interval '24 hours'"),
            R.c.cause.like("programmes:%"))).scalar()
    if n >= CHANGES_PER_DAY:
        raise SwapLimit(f"at most {CHANGES_PER_DAY} programme changes a day; try again tomorrow")


def swap(plans, student_ref: str, plan_id: int, out_ref: str, in_ref: str) -> int | None:
    """Replaces one programme with another at the same rank, with the student's OK (the screens ask first)."""
    contract = _own(plans, student_ref, plan_id)
    refs = [p.programme_ref for p in contract.programmes]
    if out_ref not in refs:
        raise NotAllowed(f"{out_ref} is not in your plan")
    if in_ref in refs:
        raise NotAllowed(f"{in_ref} is already in your plan")
    book = plans._pinned(plan_id)
    year = contract.target_intake.year
    _check_programmes(plans, book.key, year, [in_ref])
    with plans.engine.connect() as conn:
        facts = conn.execute(select(func.count()).select_from(F).where(
            F.c.tenant_id == plans.kernel.tenant_id, F.c.scope == "programme", F.c.ref == in_ref,
            F.c.intake_year == year)).scalar()
    if not facts:
        raise NotAllowed(f"{in_ref} is still being researched")
    _not_started(plans, plan_id, out_ref)
    _within_limit(plans, plan_id)
    new = [ProgrammeChoice(programme_ref=in_ref if p.programme_ref == out_ref else p.programme_ref, rank=p.rank)
           for p in contract.programmes]
    return plans.change_programmes(plan_id, new, f"programmes:swap:{out_ref}->{in_ref}")


def remove(plans, student_ref: str, plan_id: int, ref: str) -> int | None:
    """Drops one programme while nothing for it has started; at least one stays (Q3)."""
    contract = _own(plans, student_ref, plan_id)
    refs = [p.programme_ref for p in sorted(contract.programmes, key=lambda p: p.rank)]
    if ref not in refs:
        raise NotAllowed(f"{ref} is not in your plan")
    if len(refs) == 1:
        raise NotAllowed("this is the last programme in your plan; swap it instead")
    _not_started(plans, plan_id, ref)
    _within_limit(plans, plan_id)
    new = [ProgrammeChoice(programme_ref=r, rank=i + 1) for i, r in enumerate(x for x in refs if x != ref)]
    return plans.change_programmes(plan_id, new, f"programmes:remove:{ref}")
