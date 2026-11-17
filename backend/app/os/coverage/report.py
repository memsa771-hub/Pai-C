"""The coverage report of one intake and the launch-gate reading (P2 spec §4.9; master R-34, R-35, R-66).

Two different questions are asked here and must not be mixed up:
- the *coverage level* of an institution (T2, R-34) reads the facts that are the institution's OWN (its, its campuses' and
  its programmes' general rows): `verified` needs those, whoever else holds a copy of the same value;
- the *floor reading* (R-35b) asks whether the facts a student needs are verified wherever their owner keeps them, so no value has to
  be copied onto an institution: the facts of the admission systems that admit it (with their tests, categories and
  calendars) and the rows an owning body holds about its programmes count, by the same ownership resolution as the level
  (`registry.coverage.ownership`). A floor field is chosen by fact CLASS (`floor_classes`), so a fact with an explicit class
  under another field name is not missed; `floor_fields` only names the keys to mark `missing` when nothing is held.

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
from app.os.knowledge.sources.allowlist import SourceDomains
from app.os.registry.coverage import coverage_map, ownership
from app.os.registry.model import NATIONAL
from app.os.registry.store import RegistryStore

R, F, P, SD, RI = models.registry, models.knowledge_facts, models.programmes, models.source_domains, models.review_items
GATES = ("a", "b", "c", "d", "e")


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


def _class_of(field_: str, explicit: str | None) -> str:
    try:
        return fact_class(field_, explicit)
    except ValueError:
        return UNCLASSIFIED


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def build(engine: Engine, tenant_id: str, intake_id: int, now: datetime) -> Report:
    intake = IntakeStore(engine, tenant_id).by_id(intake_id)
    if intake is None:
        raise IntakeError(f"no intake {intake_id}")
    exp = expected.for_family(intake.family)
    floor_classes = set(exp.floor_classes)
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

    owned: dict = {}
    own: set = set()
    rows_by_ref: dict[tuple[str, str], list] = defaultdict(list)  # every fact of the intake, any owner
    if insts:
        with engine.connect() as conn:
            owned, own = ownership(conn, tenant_id, insts)
            by_scope: dict[str, list[str]] = defaultdict(list)
            for scope, ref in owned:
                by_scope[scope].append(ref)
            for scope, refs in by_scope.items():
                for f in conn.execute(select(F).where(
                        F.c.tenant_id == tenant_id, F.c.scope == scope, F.c.ref.in_(refs),
                        F.c.intake_year == intake.year, F.c.intake_term == intake.term).order_by(F.c.id)):
                    rows_by_ref[(scope, f.ref)].append(f)
    # an institution's own refs in this family: itself, its campuses, its family's programmes
    mine: dict[str, set] = {i: {("registry", i)} for i in insts}
    for (scope, ref), who in owned.items():
        if (scope, ref) in own:
            for i in who:
                if scope == "programme" and ref not in prog_refs.get(i, ()):
                    continue  # a programme of another family is not this intake's
                mine[i].add((scope, ref))
    shared_regs = {i: {ref for (scope, ref), who in owned.items() if scope == "registry" and i in who} for i in insts}

    held: dict[str, dict] = defaultdict(dict)  # the institution's own general high-stakes facts: key -> row
    own_any: dict[str, list] = defaultdict(list)  # own facts of any owner whose class is a floor class
    for i in insts:
        for scope, ref in mine[i]:
            for f in rows_by_ref.get((scope, ref), ()):
                if f.owner_ref == "" and _high(f.field, f.fact_class):
                    held[i][(scope, ref, f.field)] = f
                if _class_of(f.field, f.fact_class) in floor_classes:
                    own_any[i].append(f)
    owner_of = {(s, r): i for i in insts for (s, r) in mine[i]}
    slot_floor: dict[str, set] = defaultdict(set)
    for slot in slot_report(engine, tenant_id, intake.id):
        owner = owner_of.get((slot.scope, slot.ref))
        if owner and _class_of(slot.field, slot.fact_class) in floor_classes:
            slot_floor[owner].add((slot.scope, slot.ref, slot.field))

    def required(i: str) -> set:
        targets = [("programme", ref) for ref in prog_refs.get(i, [])] or [("registry", i)]
        keys = {(s, r, f) for s, r in targets for f in exp.floor_fields}  # absent expected keys: marked missing
        keys |= {(f.scope, f.ref, f.field) for f in own_any[i]}
        return keys | slot_floor[i]

    def best(i: str, key: tuple) -> str | None:
        """`verified` when the field is verified wherever its owner keeps it: on the key's own entity (any owner) or
        on an institution-level, campus or shared registry entity; else the best other status; None when absent."""
        scope, ref, field_ = key
        rank = {"verified": 3, "confirmed": 2, "unconfirmed": 1, "stale": 0}
        found = [f for f in rows_by_ref.get((scope, ref), ()) if f.field == field_]
        for r in shared_regs[i] | {x for s, x in mine[i] if s == "registry"}:
            found += [f for f in rows_by_ref.get(("registry", r), ()) if f.field == field_]
        return max((f.status for f in found), key=lambda st: rank.get(st, 0), default=None)

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
        req = required(i)
        for key in sorted(req):
            st = best(i, key)
            if st is None:
                row.hs_missing += 1
            elif st == "verified":
                row.hs_verified += 1
            else:
                row.hs_not_confirmed += 1
        for key, f in sorted(held[i].items()):  # the other own high-stakes facts
            if key in req:
                continue
            if f.status == "verified":
                row.hs_verified += 1
            else:
                row.hs_not_confirmed += 1

    # (a) the denominator: the regional and national official lists, per institution type
    reg = RegistryStore(engine, tenant_id)
    wanted_types = sorted({*by_type, *exp.institution_types} - {""})
    entries = {e.entity_id: e for e in reg.list(kind="official_list", limit=10_000)}
    progress = [p for p in reg.list_progresses() if p.list_id in entries]
    a = Reading("a", "Denominator: official lists per region and institution type, dated, 100% loaded")
    for t in wanted_types:
        lists = [p for p in progress if entries[p.list_id].institution_type == t
                 and entries[p.list_id].region in (intake.region, NATIONAL, None)
                 and entries[p.list_id].attrs.get("family") in (None, "", intake.family)]
        row = by_type.setdefault(t, TypeRow(t))
        row.lists = [{"list_id": p.list_id, "name": p.name, "region": p.region, "published": p.published,
                      "loaded": p.loaded, "count_confirmed": p.count_confirmed,
                      "date": entries[p.list_id].attrs.get("date")} for p in lists]
        a.checked += 1
        if not lists:
            a.items.append(Item("no_list", t, "no official list for this institution type"))
        for p in lists:  # several lists for one type are fine: each has to be dated, confirmed and complete
            if not entries[p.list_id].attrs.get("date"):
                a.items.append(Item("no_date", p.list_id, "the list has no date"))
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
        if term_year not in (r.attrs.get("first_live") or []):
            continue
        b.checked += 1
        for key in sorted(required(i)):
            st = best(i, key)
            if st == "verified":
                continue
            if st is None:
                b.items.append(Item("missing", f"{i} {key[1]} {key[2]}"))
            else:
                b.items.append(Item("not_verified", f"{i} {key[1]} {key[2]}", st))

    sources = SourceDomains(engine, tenant_id)
    c_read = Reading("c", "Everything else high-stakes is verified or not confirmed with a link on a listed official domain")
    for i in insts:
        for key, f in sorted(held[i].items()):
            c_read.checked += 1
            if f.status == "verified":
                continue
            if not (f.url.strip() and f.quote.strip()):
                c_read.items.append(Item("no_link", f"{i} {key[1]} {key[2]}", "not confirmed and no official link"))
            else:  # R-24: only a listed official domain counts as a source; a suspect one fails too
                st = sources.state_of(_host(f.url))
                if st is None:
                    c_read.items.append(Item("not_official_domain", f"{i} {key[1]} {key[2]}",
                                             f"{_host(f.url)} is on no allow-list"))
                elif st.state == "suspect":
                    c_read.items.append(Item("suspect_domain", f"{i} {key[1]} {key[2]}", f"{st.domain} is suspect"))

    d = Reading("d", "No online information: stays listed, offered only as 'PAI can't run this place yet'")
    for i, r in insts.items():
        if r.attrs.get("not_readable"):
            d.checked += 1
            if cov[i].level != "listed":
                d.items.append(Item("not_verified", i, f"level {cov[i].level} for a place with no official information"))

    # (e) an intake that is already current must stay green; it is flagged, never reverted by itself
    e = Reading("e", "A current intake keeps passing its gate (flagged, not reverted)")
    if intake.state == "current":
        e.checked = 1
        failing = sum(len(r.items) for r in (a, b, c_read, d))
        if failing:
            e.items.append(Item("gate_turned_red", f"intake {intake.id}", f"{failing} item(s) fail since the gate passed"))

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
    return Report(intake, [by_type[k] for k in sorted(by_type)], [a, b, c_read, d, e], suspect, opens, load)
