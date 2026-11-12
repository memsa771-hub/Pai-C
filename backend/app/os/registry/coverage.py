"""Coverage level of an institution (P2 spec §4.1; master R-34). Computed from the facts of the coming intake, never
stored:

- `listed`: the institution is in the registry;
- `researched`: at least one fact (any status) for the intake, own or shared;
- `verified`: at least one high-stakes fact of its OWN, and every high-stakes fact of its own `verified`.

Own facts are those about the institution itself, its campuses and its programmes. Only general rows count there
(`owner_ref == ''`): a row a body owns about a programme or campus is the body's value, not research of that programme
(P2-D8). Shared facts are those about the admission systems that admit the institution (or its programmes), with their
tests, seat categories and calendars. They count toward `researched` only: they are the same facts for every
institution that system admits, so they can neither make an institution `verified` nor hold it back. A body's own
facts are not counted at all: they belong to every institution it serves. An institution with no official online
information (`attrs.not_readable`) stays `listed` (R-35d).

This is a deliberate, weaker answer than "every expected field is verified". Which facts are *expected* of an
institution is the coverage gate's business (T9, the expected-field gate); that gate is the full answer, and this
level only reads what exists."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import Engine, and_, func, or_, select

from app.os import models
from app.os.knowledge.fact_classes import UNCLASSIFIED, fact_class, is_high_stakes

LEVELS = ("listed", "researched", "verified")
R = models.registry
L = models.registry_links
P = models.programmes
F = models.knowledge_facts


@dataclass(frozen=True)
class Coverage:
    entity_id: str
    level: str
    facts: int
    high_stakes: int
    high_stakes_verified: int
    not_readable: bool = False
    shared_facts: int = 0  # facts of the admitting systems, tests, categories and calendars (counted in `facts`)


def _high_stakes(field: str, explicit: str | None) -> bool:
    try:
        return is_high_stakes(fact_class(field, explicit))
    except ValueError:  # an unknown class on a stored row is treated as unclassified: high-stakes (fail safe)
        return is_high_stakes(UNCLASSIFIED)


def ownership(conn, tenant_id: str, insts) -> tuple[dict, set]:
    """Whose facts count for which institution (the one resolution used by the level and by the launch gate): the map
    (fact scope, ref) -> institutions it counts for, and the set of the institutions' own refs (the institutions, their
    campuses and their programmes). Admission systems that admit an institution, a campus or one of its programmes, with
    their tests, seat categories, calendars and children, are shared, not own."""
    owned: dict[tuple[str, str], set[str]] = defaultdict(set)  # (fact scope, ref) -> institutions it counts for
    own: set[tuple[str, str]] = set()  # the institutions, campuses and programmes: facts of the institution itself
    for i in insts:
        owned[("registry", i)].add(i)
        own.add(("registry", i))
    campus_of: dict[str, str] = {}
    for r in conn.execute(select(R.c.entity_id, R.c.parent_id).where(
            R.c.tenant_id == tenant_id, R.c.kind == "campus", R.c.parent_id.in_(list(insts)))):
        owned[("registry", r.entity_id)].add(r.parent_id)
        campus_of[r.entity_id] = r.parent_id
        own.add(("registry", r.entity_id))
    for r in conn.execute(select(P.c.ref, P.c.institution_id).where(
            P.c.tenant_id == tenant_id, P.c.institution_id.in_(list(insts)))):
        owned[("programme", r.ref)].add(r.institution_id)
        own.add(("programme", r.ref))
    # admission systems that admit an institution, a campus, or one of its programmes
    admitted: dict[str, set[str]] = defaultdict(set)  # system -> institutions
    for r in conn.execute(select(L.c.from_id, L.c.to_kind, L.c.to_id).where(
            L.c.tenant_id == tenant_id, L.c.rel == "admits")):
        if r.to_kind == "registry":
            target = r.to_id if r.to_id in insts else campus_of.get(r.to_id)
            if target:
                admitted[r.from_id].add(target)
        else:
            admitted[r.from_id].update(owned.get(("programme", r.to_id), ()))
    admitted = {k: v for k, v in admitted.items() if v}
    if admitted:
        for system, owners in admitted.items():
            owned[("registry", system)].update(owners)
        for r in conn.execute(select(L.c.from_id, L.c.to_id).where(
                L.c.tenant_id == tenant_id, L.c.rel.in_(("uses_test", "has_category")),
                L.c.from_id.in_(list(admitted)), L.c.to_kind == "registry")):
            owned[("registry", r.to_id)].update(admitted[r.from_id])
        for r in conn.execute(select(R.c.entity_id, R.c.parent_id).where(
                R.c.tenant_id == tenant_id, R.c.parent_id.in_(list(admitted)))):
            owned[("registry", r.entity_id)].update(admitted[r.parent_id])
    return owned, own


def coverage_map(engine: Engine, tenant_id: str, intake_year: int, *, intake_term: str | None = None,
                 region: str | None = None) -> dict[str, Coverage]:
    """The coverage of every active institution (of one region if given) for the intake. `intake_term=None` reads
    facts of every term of that year."""
    with engine.connect() as conn:
        q = select(R.c.entity_id, R.c.attrs).where(R.c.tenant_id == tenant_id, R.c.kind == "institution",
                                                   R.c.status == "active")
        if region:
            q = q.where(R.c.region == region)
        insts = {r.entity_id: bool(r.attrs.get("not_readable")) for r in conn.execute(q.order_by(R.c.id))}
        if not insts:
            return {}
        owned, own = ownership(conn, tenant_id, insts)
        by_scope: dict[str, list[str]] = defaultdict(list)
        for scope, ref in owned:
            by_scope[scope].append(ref)
        fq = select(F.c.scope, F.c.ref, F.c.field, F.c.status, F.c.fact_class, F.c.owner_ref).where(
            F.c.tenant_id == tenant_id, F.c.intake_year == intake_year,
            or_(*[and_(F.c.scope == scope, F.c.ref.in_(refs)) for scope, refs in by_scope.items()]))
        if intake_term is not None:
            fq = fq.where(F.c.intake_term == intake_term)
        # a fact withdrawn by an import undo (stale, empty value) is not a fact for the intake (P2-T6)
        withdrawn = and_(F.c.status == "stale", or_(F.c.value.is_(None), func.jsonb_typeof(F.c.value) == "null"))
        facts = conn.execute(fq.where(~withdrawn)).all()
    count = {i: [0, 0, 0, 0] for i in insts}  # facts, own high-stakes, own high-stakes verified, shared facts
    for f in facts:
        is_own = (f.scope, f.ref) in own
        if is_own and f.owner_ref != "":  # a body's row about the institution, its campus or programme
            continue
        hs = is_own and _high_stakes(f.field, f.fact_class)
        for i in owned[(f.scope, f.ref)]:
            c = count[i]
            c[0] += 1
            if not is_own:
                c[3] += 1
            elif hs:
                c[1] += 1
                c[2] += f.status == "verified"
    out = {}
    for i, not_readable in insts.items():
        n, hs, ok, shared = count[i]
        level = "listed" if n == 0 or not_readable else "verified" if hs and ok == hs else "researched"
        out[i] = Coverage(i, level, n, hs, ok, not_readable, shared)
    return out


def summarise(coverage: dict[str, Coverage]) -> dict[str, int]:
    """How many institutions are at each level."""
    out = dict.fromkeys(LEVELS, 0)
    for c in coverage.values():
        out[c.level] += 1
    return out
