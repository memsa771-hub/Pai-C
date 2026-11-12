"""ProgrammeList v2 (P2 spec P2-D27, §4.1; master R-34, R-35d): v1's places plus each one's coverage level, region and
whether PAI can run it yet.

Coverage is computed, never stored: `listed` (the row exists), `researched` (at least one fact for the intake),
`verified` (every high-stakes fact the route needs, and any other held, is verified). The region comes from the
registry (T2): the programme's own region, else its institution's. For a programme in the registry the level is the lower
of its own and its institution's (T2's `coverage_map`, so a `not_readable` institution stays `listed`, R-35d). A place
with no fact for the intake is `not_run_yet`."""

from sqlalchemy import Engine, select

from app.os import models
from app.os.compiler.compile import needed_fields
from app.os.contracts.programme_list_v2 import ProgrammeEntryV2, ProgrammeListV2
from app.os.contracts.route_contract import IntakeRef
from app.os.knowledge.fact_classes import fact_class, is_high_stakes
from app.os.knowledge.programmes import ProgrammeStore
from app.os.playbooks import newest_plain
from app.os.registry.coverage import LEVELS, coverage_map

K = models.knowledge_facts
# Coverage counts real fact rows only (M8): a row with no value is a placeholder, and rows that come from an import line
# which only names a lead or was rejected or superseded are not facts. Today's table cannot hold those statuses; the
# set keeps the rule if a later task adds them.
NOT_FACT_STATUSES = frozenset({"lead_only", "rejected", "superseded", "not_found"})


def build(engine: Engine, tenant_id: str, books, route_key: str, intake: IntakeRef) -> ProgrammeListV2:
    book = newest_plain(books.values()).get(route_key)
    if book is None:
        return ProgrammeListV2(route_key=route_key, intake=intake, programmes=[])
    needed = sorted(needed_fields(book)[1])
    programmes = ProgrammeStore(engine, tenant_id).active(route_key)
    with engine.connect() as conn:
        rows = conn.execute(select(K).where(
            K.c.tenant_id == tenant_id, K.c.scope == "programme", K.c.ref.in_([p.ref for p in programmes] or [""]),
            K.c.intake_year == intake.year, K.c.intake_term.in_([intake.term, ""])).order_by(K.c.id)).all()
    held: dict[tuple[str, str], object] = {}
    for r in rows:
        if r.value is None or r.status in NOT_FACT_STATUSES:
            continue
        # one row per (programme, field): the asked term beats an unrecorded one, then the newest
        key = (r.ref, r.field)
        if key not in held or (r.intake_term == intake.term) >= (held[key].intake_term == intake.term):
            held[key] = r
    cover = coverage_map(engine, tenant_id, intake.year, intake_term=intake.term) \
        if any(p.institution_id for p in programmes) else {}
    with engine.connect() as conn:
        regions = dict(conn.execute(select(models.registry.c.entity_id, models.registry.c.region).where(
            models.registry.c.tenant_id == tenant_id, models.registry.c.kind == "institution")).all())
    entries = []
    for p in programmes:
        mine = {f: r for (ref, f), r in held.items() if ref == p.ref}
        confirmed = all(f in mine and mine[f].status in ("confirmed", "verified") for f in needed)
        high = {f for f in set(needed) | set(mine)
                if is_high_stakes(fact_class(f, mine[f].fact_class if f in mine else None))}
        level = ("verified" if mine and high and all(f in mine and mine[f].status == "verified" for f in high)
                 else "researched" if mine else "listed")
        inst = cover.get(p.institution_id) if p.institution_id else None
        if inst is not None:  # the lower of the two: an institution that is not readable cannot make a place verified
            level = min(level, inst.level, key=LEVELS.index)
        entries.append(ProgrammeEntryV2(
            programme_ref=p.ref, university=p.university, name=p.name, facts_confirmed=confirmed,
            coverage_level=level, region=p.region or regions.get(p.institution_id) or None, not_run_yet=level == "listed"))
    return ProgrammeListV2(route_key=route_key, intake=intake, programmes=entries)


