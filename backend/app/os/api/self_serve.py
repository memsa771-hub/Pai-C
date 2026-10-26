"""Reads for the self-serve screens (Slice 4 spec §4): routes, the route's programmes with the student's eligibility
cards, one card with swap suggestions, and the plan with its programmes. Reads only; plans change in routes.builder.
"""

from dataclasses import asdict, dataclass

from sqlalchemy import exists, select

from app.os.kernel.states import PLAN_OPEN
from app.os import models
from app.os.api.queries import plan_out
from app.os.eligibility.evaluate import Card
from app.os.eligibility.notes import profile_of, programme_cards
from app.os.eligibility.swaps import suggest
from app.os.knowledge.programmes import _programme
from app.os.knowledge.requests import requested_without_facts, visible_programmes

G, F, RQ, P = models.programmes, models.knowledge_facts, models.programme_requests, models.plans


def newest_books(plans) -> dict:
    out = {}
    for (key, _), book in plans.playbooks.items():
        if key not in out or book.version > out[key].version:
            out[key] = book
    return out


def routes_out(plans) -> list[dict]:
    return [{"key": b.key, "version": b.version, "origin": b.route.origin, "destination": b.route.destination,
             "level": b.route.level} for _, b in sorted(newest_books(plans).items())]


def card_out(card: Card | None) -> dict | None:
    return None if card is None else asdict(card)


def _requested_by(plans, student_ref: str, route_key: str, year: int) -> list:
    """Programmes this student asked for that research has found nothing for yet (they see them as being researched)."""
    tenant = plans.kernel.tenant_id
    has_facts = exists(select(F.c.id).where(F.c.tenant_id == tenant, F.c.scope == "programme", F.c.ref == G.c.ref,
                                            F.c.intake_year == year))
    asked = select(RQ.c.programme_ref).where(RQ.c.tenant_id == tenant, RQ.c.student_ref == student_ref)
    with plans.engine.connect() as conn:
        rows = conn.execute(select(G).where(G.c.tenant_id == tenant, G.c.route_key == route_key,
                                            G.c.status == "requested", ~has_facts, G.c.ref.in_(asked))
                            .order_by(G.c.ref)).all()
    return [_programme(r) for r in rows]


def route_programmes(plans, student_ref: str, route_key: str, year: int) -> list[dict] | None:
    """None if the route is unknown."""
    book = newest_books(plans).get(route_key)
    if book is None:
        return None
    visible = visible_programmes(plans.engine, plans.kernel.tenant_id, route_key, year)
    rules = book.eligibility
    cards = (programme_cards(plans, rules, [p.ref for p in visible], year, profile_of(plans, student_ref))
             if rules is not None else {})
    with plans.engine.connect() as conn:
        researched = set(conn.execute(select(F.c.ref).distinct().where(
            F.c.tenant_id == plans.kernel.tenant_id, F.c.scope == "programme", F.c.intake_year == year,
            F.c.ref.in_([p.ref for p in visible]))).scalars())
    out = []
    for p in visible:
        card, confirmed = cards.get(p.ref, (None, 0))
        out.append({"ref": p.ref, "university": p.university, "name": p.name,
                    "research_state": "researched" if p.ref in researched else "being_researched",
                    "requested_by_student": p.status == "requested", "confirmed_facts": confirmed,
                    "card": card_out(card) if p.ref in researched else None})
    for p in _requested_by(plans, student_ref, route_key, year):
        out.append({"ref": p.ref, "university": p.university, "name": p.name, "research_state": "being_researched",
                    "requested_by_student": True, "confirmed_facts": 0, "card": None})
    return out


def _chosen(plans, student_ref: str, route_key: str, year: int) -> set[str]:
    """The programmes already in the student's plan for this route and intake."""
    with plans.engine.connect() as conn:
        rows = conn.execute(select(P.c.contract).where(
            P.c.tenant_id == plans.kernel.tenant_id, P.c.student_ref == student_ref,
            P.c.contract["target_intake"]["year"].as_integer() == year)).scalars().all()
    book = newest_books(plans).get(route_key)
    return {c["programme_ref"] for contract in rows for c in contract.get("programmes", [])
            if book and (contract["destination_country"], contract["level"]) ==
            (book.route.destination, book.route.level)}


def eligibility(plans, student_ref: str, programme_ref: str, route_key: str, year: int) -> dict | None:
    """One programme's card with up to 3 swap suggestions. None if the route or programme is unknown."""
    book = newest_books(plans).get(route_key)
    if book is None:
        return None
    visible = {p.ref: p for p in visible_programmes(plans.engine, plans.kernel.tenant_id, route_key, year)}
    if programme_ref not in visible:
        return None
    if book.eligibility is None:
        return {"card": None, "suggestions": []}
    cards = programme_cards(plans, book.eligibility, list(visible), year, profile_of(plans, student_ref))
    card = cards[programme_ref][0]
    picks = suggest(card, list(cards.values()), _chosen(plans, student_ref, route_key, year))
    return {"card": card_out(card), "suggestions": [
        {"programme_ref": s.programme_ref, "university": visible[s.programme_ref].university,
         "name": visible[s.programme_ref].name, "confirmed_facts": s.confirmed_facts} for s in picks]}


def self_plan_out(plans, plan_id: int) -> dict:
    out = plan_out(plans.engine, plans.kernel.tenant_id, plan_id)
    contract, _ = plans._contract(plan_id)
    out["programmes"] = [{"programme_ref": p.programme_ref, "rank": p.rank}
                         for p in sorted(contract.programmes, key=lambda p: p.rank)]
    return out


def requested_programmes_out(plans) -> list[dict]:
    return [{"ref": p.ref, "route_key": p.route_key, "university": p.university, "name": p.name,
             "start_urls": list(p.start_urls)} for p in requested_without_facts(plans.engine, plans.kernel.tenant_id)]


@dataclass(frozen=True)
class StudentPlan:
    plan_id: int
    route_key: str
    year: int
    programmes: tuple[str, ...]


def student_plan(plans, student_ref: str) -> StudentPlan | None:
    """The student's newest open plan and the route it follows (Slice 5: statements belong to a route)."""
    with plans.engine.connect() as conn:
        rows = conn.execute(select(P.c.id, P.c.contract).where(
            P.c.tenant_id == plans.kernel.tenant_id, P.c.student_ref == student_ref, P.c.status.in_(PLAN_OPEN))
            .order_by(P.c.id.desc())).all()
    books = newest_books(plans)
    for row in rows:
        c = row.contract
        for key, b in sorted(books.items()):
            if (b.route.origin, b.route.destination, b.route.level) == (
                    c["origin_country"], c["destination_country"], c["level"]):
                return StudentPlan(row.id, key, c["target_intake"]["year"],
                                   tuple(p["programme_ref"] for p in sorted(c["programmes"], key=lambda p: p["rank"])))
    return None
