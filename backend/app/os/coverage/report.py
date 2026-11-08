"""The coverage report of one intake and the launch-gate reading (P2 spec §4.9; master R-34, R-35, R-66).

An intake is a region, family, term and year (`os_intakes`). The report shows, per institution type: the official lists
(the denominator), how many institutions are listed / researched / verified, and the high-stakes facts verified, not
confirmed and missing. Four readings (R-35 a to d) are green or red, each red with its failing items. Everything is
computed from the registry, Knowledge, the review queue and the intake slots; nothing is stored."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Engine, func, select

from app.os import models
from app.os.coverage import expected, workload
from app.os.intakes.rollover import slot_report
from app.os.intakes.store import Intake, IntakeError, IntakeStore
from app.os.knowledge.fact_classes import UNCLASSIFIED, fact_class, is_high_stakes
from app.os.registry.coverage import coverage_map
from app.os.registry.model import NATIONAL
from app.os.registry.store import RegistryStore

R, F, P, SD, RI = models.registry, models.knowledge_facts, models.programmes, models.source_domains, models.review_items
GATES = ("a", "b", "c", "d")


@dataclass(frozen=True)
class Item:
    code: str  # no_list | count_unconfirmed | list_incomplete | list_over | not_verified | missing | no_link
    subject: str
    detail: str = ""


@dataclass
class Reading:
    gate: str
    title: str
    checked: int = 0
    items: list[Item] = field(default_factory=list)

    @property
    def green(self) -> bool:
        return not self.items


@dataclass
class TypeRow:
    institution_type: str
    institutions: int = 0
    listed: int = 0
    researched: int = 0
    verified: int = 0
    lists: list[dict] = field(default_factory=list)
    hs_verified: int = 0
    hs_not_confirmed: int = 0
    hs_missing: int = 0
    not_readable: int = 0


@dataclass
class Report:
    intake: Intake
    rows: list[TypeRow]
    readings: list[Reading]
    suspect_domains: list[str]
    open_review_items: dict[str, int]
    workload: workload.Workload

    @property
    def green(self) -> bool:
        return all(r.green for r in self.readings)

    def failing(self) -> list[dict]:
        return [{"gate": r.gate, "code": i.code, "subject": i.subject, "detail": i.detail}
                for r in self.readings for i in r.items]


def _high(field_: str, explicit: str | None) -> bool:
    try:
        return is_high_stakes(fact_class(field_, explicit))
    except ValueError:  # an unknown class on a stored row: unclassified, which is high-stakes
        return is_high_stakes(UNCLASSIFIED)


def build(engine: Engine, tenant_id: str, intake_id: int, now: datetime) -> Report:
    intake = IntakeStore(engine, tenant_id).by_id(intake_id)
    if intake is None:
        raise IntakeError(f"no intake {intake_id}")
    exp = expected.for_family(intake.family)
    nationwide = intake.region == NATIONAL
    with engine.connect() as conn:
        q = select(R).where(R.c.tenant_id == tenant_id, R.c.kind == "institution", R.c.status == "active")
        if not nationwide:
            q = q.where(R.c.region == intake.region)
        insts = {r.entity_id: r for r in conn.execute(q.order_by(R.c.id))}
        progs = conn.execute(select(P.c.ref, P.c.institution_id, P.c.family).where(
            P.c.tenant_id == tenant_id, P.c.institution_id.in_(list(insts) or [""]))).all()
    in_family = {p.institution_id for p in progs if p.family == intake.family} | {
        i for i, r in insts.items() if r.attrs.get("family") == intake.family}
    insts = {i: r for i, r in insts.items() if i in in_family}
    prog_refs: dict[str, list[str]] = defaultdict(list)
    for p in progs:
        if p.family == intake.family and p.institution_id in insts:
            prog_refs[p.institution_id].append(p.ref)
    with engine.connect() as conn:
        campuses = conn.execute(select(R.c.entity_id, R.c.parent_id).where(
            R.c.tenant_id == tenant_id, R.c.kind == "campus", R.c.parent_id.in_(list(insts) or [""]))).all()
    campus_of = {c.entity_id: c.parent_id for c in campuses}
    owner_of: dict[tuple[str, str], str] = {("registry", i): i for i in insts}
    owner_of.update({("registry", c): i for c, i in campus_of.items()})
    owner_of.update({("programme", ref): i for i, refs in prog_refs.items() for ref in refs})

    # the institution's own, general (owner '') facts of this intake that are high-stakes: scope/ref/field -> row
    held: dict[str, dict[tuple[str, str, str], object]] = defaultdict(dict)
    if owner_of:
        with engine.connect() as conn:
            for scope in ("registry", "programme"):
                refs = [r for (s, r) in owner_of if s == scope]
                if not refs:
                    continue
                for f in conn.execute(select(F).where(
                        F.c.tenant_id == tenant_id, F.c.scope == scope, F.c.ref.in_(refs), F.c.intake_year == intake.year,
                        F.c.intake_term == intake.term, F.c.owner_ref == "").order_by(F.c.id)):
                    if _high(f.field, f.fact_class):
                        held[owner_of[(scope, f.ref)]][(scope, f.ref, f.field)] = f
    slot_keys: dict[str, set] = defaultdict(set)
    for slot in slot_report(engine, tenant_id, intake.id):
        owner = owner_of.get((slot.scope, slot.ref))
        if owner and slot.owner_ref == "" and _high(slot.field, slot.fact_class):
            slot_keys[owner].add((slot.scope, slot.ref, slot.field))

    def floor_keys(inst: str) -> set:
        targets = [("programme", ref) for ref in prog_refs.get(inst, [])] or [("registry", inst)]
        return {(s, r, f) for s, r in targets for f in exp.floor_fields}

    def floor_met(inst: str, key: tuple) -> bool:
        """A floor field is met by the programme's own verified fact, or by a verified fact of its institution."""
        ok = lambda k: getattr(held[inst].get(k), "status", None) == "verified"
        return ok(key) or ok(("registry", inst, key[2]))

    cov = coverage_map(engine, tenant_id, intake.year, intake_term=intake.term,
                       region=None if nationwide else intake.region)
    by_type: dict[str, TypeRow] = {}
    for i, r in insts.items():
        row = by_type.setdefault(r.institution_type or "", TypeRow(r.institution_type or ""))
        c = cov.get(i)
        level = c.level if c else "listed"
        row.institutions += 1
        setattr(row, level, getattr(row, level) + 1)
        row.not_readable += bool(r.attrs.get("not_readable"))
        keys = floor_keys(i) | slot_keys[i] | set(held[i])
        for key in sorted(keys):
            got = held[i].get(key)
            if got is None and key in floor_keys(i) and key[0] == "programme" and floor_met(i, key):
                row.hs_verified += 1
            elif got is None:
                row.hs_missing += 1
            elif got.status == "verified":
                row.hs_verified += 1
            else:
                row.hs_not_confirmed += 1

    # lists: the regional ones and the national ones, per institution type (R-35a)
    reg = RegistryStore(engine, tenant_id)
    wanted_types = sorted({*by_type, *exp.institution_types} - {""})
    entries = {e.entity_id: e for e in reg.list(kind="official_list", limit=10_000)}
    progress = [p for p in reg.list_progresses() if p.list_id in entries]
    a = Reading("a", "Denominator: one official list per region and institution type, 100% loaded")
    for t in wanted_types:
        lists = [p for p in progress if entries[p.list_id].institution_type == t
                 and entries[p.list_id].region in (intake.region, NATIONAL, None)
                 and entries[p.list_id].attrs.get("family") in (None, "", intake.family)]
        row = by_type.setdefault(t, TypeRow(t))
        row.lists = [{"list_id": p.list_id, "name": p.name, "region": p.region, "published": p.published,
                      "loaded": p.loaded, "count_confirmed": p.count_confirmed} for p in lists]
        a.checked += 1
        if not lists:
            a.items.append(Item("no_list", t, "no official list for this institution type"))
        for p in lists:
            if not p.count_confirmed or p.published is None:
                a.items.append(Item("count_unconfirmed", p.list_id, "the published count is not confirmed"))
            elif p.over:
                a.items.append(Item("list_over", p.list_id, f"{p.loaded} loaded, {p.published} published"))
            elif not p.complete:
                a.items.append(Item("list_incomplete", p.list_id, f"{p.loaded} of {p.published} loaded"))
    if not wanted_types:
        a.items.append(Item("no_list", intake.region, "no institution and no expected type for this region and family"))

    term_year = f"{intake.term}:{intake.year}"
    b = Reading("b", "Verified floor: deadlines, merit formulas, thresholds of first-live institutions")
    for i, r in insts.items():
        live = r.attrs.get("first_live") or []
        if term_year not in live:
            continue
        b.checked += 1
        for key in sorted(floor_keys(i) | slot_keys[i]):
            if key in floor_keys(i) and floor_met(i, key):
                continue
            got = held[i].get(key)
            if got is None:
                b.items.append(Item("missing", f"{i} {key[1]} {key[2]}"))
            elif got.status != "verified":
                b.items.append(Item("not_verified", f"{i} {key[1]} {key[2]}", got.status))

    c_read = Reading("c", "Everything else high-stakes is verified or not confirmed with the official link")
    for i in insts:
        for key, f in sorted(held[i].items()):
            c_read.checked += 1
            if f.status != "verified" and not (f.url.strip() and f.quote.strip()):
                c_read.items.append(Item("no_link", f"{i} {key[1]} {key[2]}", "not confirmed and no official link"))

    d = Reading("d", "No online information: stays listed, offered only as 'PAI can't run this place yet'")
    for i, r in insts.items():
        if r.attrs.get("not_readable"):
            d.checked += 1
            if cov[i].level != "listed":
                d.items.append(Item("not_verified", i, f"level {cov[i].level} for a place with no official information"))

    with engine.connect() as conn:
        suspect = [s.domain for s in conn.execute(select(SD.c.domain, SD.c.region, SD.c.family).where(
            SD.c.tenant_id == tenant_id, SD.c.state == "suspect").order_by(SD.c.domain))
            if s.region in ("", intake.region) and s.family in ("", intake.family)]
        opens = dict(conn.execute(select(RI.c.kind, func.count()).where(
            RI.c.tenant_id == tenant_id, RI.c.status == "open",
            (RI.c.intake_year == intake.year) | RI.c.intake_year.is_(None),
            RI.c.intake_term.in_([intake.term, ""])).group_by(RI.c.kind)).all())

    total_hs = sum(r.hs_verified + r.hs_not_confirmed + r.hs_missing for r in by_type.values())
    left = sum(r.hs_not_confirmed + r.hs_missing for r in by_type.values())
    load = workload.estimate(engine, tenant_id, now, institutions=len(insts), high_stakes_facts=total_hs, not_verified=left)
    return Report(intake, [by_type[k] for k in sorted(by_type)], [a, b, c_read, d], suspect, opens, load)
