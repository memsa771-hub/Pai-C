"""Consistency rules 9-12 of master §9.3 (P2-T12, R-05, R-24, R-25, R-26, R-71): what a student is shown.

Each rule reads what the screens would show for the programmes in the student's open plans, in the form the ProgrammeFacts
port gives them (`programme_facts.build`: the one display rule and the labelled-year rule are applied there), and finds the
facts that break a rule:

    9.  a fact shown with a value that has no source, or whose source domain is not on the allow-list that applies to the
        programme (its region and family or its route), nor its own or its institution's official domain;
    10. a high-stakes fact (recomputed here from `fact_classes.yaml`, not taken from the entry) shown as fact unless it is
        `verified`;
    11. a fact of another intake shown without its year;
    12. a fact shown whose source domain is marked `suspect` (R-71).

A finding carries a rule number and codes `<code>:<field>`, never a value (R-01). The check reads only; the host job opens
the cases.

Limits, said plainly:
- Only programmes in open plans are covered: a fact a student could see elsewhere (a browse screen, the programme list of a
  route they have not planned) is not read here.
- Rule 9 can only be checked against a loaded allow-list, and rule 12 only exists with the source guard (it is the guard that
  marks domains suspect). When either cannot run, the run says so (`rule_status`): "not run", never a count of zero.
- Allow-list scope is the programme's region and family where the registry holds them; otherwise its route only."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import Engine, select

from app.os import models
from app.os.contracts.programme_facts import FactEntry, ProgrammeFactsV1
from app.os.contracts.route_contract import IntakeRef
from app.os.kernel.states import PLAN_OPEN
from app.os.knowledge.fact_classes import fact_class, is_high_stakes
from app.os.knowledge.research.links import domain_of
from app.os.knowledge.sources.allowlist import Scope, SourceDomains
from app.os.replan.store import OverrideStore

RULES = (9, 10, 11, 12)
P, SD, PG, RG = models.plans, models.source_domains, models.programmes, models.registry
NO_ALLOW_LIST, GUARD_OFF = "no allow-list loaded", "source guard off"


@dataclass(frozen=True)
class FactFinding:
    rule: int
    codes: tuple[str, ...]
    plan_id: int | None = None


def allow_list_loaded(engine: Engine, tenant_id: str) -> bool:
    """Whether any reviewed allow-list entry is active: without one, rule 9 has nothing to check against."""
    with engine.connect() as conn:
        return conn.execute(select(SD.c.id).where(SD.c.tenant_id == tenant_id, SD.c.state == "active",
                                                  SD.c.tier.is_not(None)).limit(1)).first() is not None


def rule_status(engine: Engine, tenant_id: str, guard_on: bool) -> dict[int, str | None]:
    """Per rule: None when it runs, else why it did not (the run reports this, never a silent zero)."""
    return {9: None if allow_list_loaded(engine, tenant_id) else NO_ALLOW_LIST, 10: None, 11: None,
            12: None if guard_on else GUARD_OFF}


def own_domains(engine: Engine, tenant_id: str, programme_ref: str) -> set[str]:
    """The registrable domains of the programme's own official domains and of its institution's registry entry."""
    with engine.connect() as conn:
        row = conn.execute(select(PG.c.official_domains, PG.c.institution_id).where(
            PG.c.tenant_id == tenant_id, PG.c.ref == programme_ref)).first()
        if row is None:
            return set()
        domains = list(row.official_domains or [])
        if row.institution_id:
            domains += list(conn.execute(select(RG.c.official_domains).where(
                RG.c.tenant_id == tenant_id, RG.c.entity_id == row.institution_id)).scalar() or [])
    return {domain_of(f"https://{d}/") for d in domains}


def _high_stakes(e: FactEntry) -> bool:
    try:
        return is_high_stakes(fact_class(e.field, e.fact_class if e.fact_class in _classes() else None))
    except ValueError:
        return True  # an unknown class is treated as unclassified: high-stakes (fail safe)


def _classes() -> set[str]:
    from app.os.knowledge.fact_classes import classes

    return set(classes())


def check_entries(entries: Iterable[FactEntry], intake: IntakeRef, listed, suspect: set[str] | None,
                  urls: Mapping[str, str] | None = None) -> dict[int, list[str]]:
    """The codes found per rule for the facts a student is shown. Only entries that carry a value are 'shown'.

    `listed(url)` says whether a source URL is allowed for the programme (None: rule 9's list is not loaded, so only the
    missing-source check runs); `suspect` is the set of suspect registrable domains (None: rule 12 does not run); `urls` are
    the facts' raw URLs by field (a fact can hold a URL the entry's SourceRef does not show)."""
    found: dict[int, list[str]] = {r: [] for r in RULES}
    for e in entries:
        if e.value is None:
            continue
        url = (urls or {}).get(e.field) or (e.source.url if e.source is not None else "")
        if not url:
            found[9].append(f"no_source:{e.field}")
        else:
            host = domain_of(url)
            if suspect is not None and host in suspect:
                found[12].append(f"suspect_domain:{e.field}")
            elif listed is not None and not listed(url):
                found[9].append(f"domain_not_listed:{e.field}")
        if _high_stakes(e) and e.level != "verified":
            found[10].append(f"high_stakes_not_verified:{e.field}")
        if e.fact_intake is not None and (e.fact_intake.year != intake.year or e.fact_intake.term not in ("", intake.term)) \
                and not e.other_intake:
            found[11].append(f"other_intake_unlabelled:{e.field}")
    return found


def open_plan_students(engine: Engine, tenant_id: str) -> list[str]:
    """Every student with an open plan of any source: rules 9-12 are about what any student is shown."""
    with engine.connect() as conn:
        return sorted(conn.execute(select(P.c.student_ref).distinct().where(
            P.c.tenant_id == tenant_id, P.c.status.in_(PLAN_OPEN))).scalars())


def suspect_domains(engine: Engine, tenant_id: str) -> set[str]:
    with engine.connect() as conn:
        return {domain_of(f"https://{d}/") for d in conn.execute(select(SD.c.domain).where(
            SD.c.tenant_id == tenant_id, SD.c.state == "suspect")).scalars()}


def student_findings(engine: Engine, tenant_id: str, knowledge, books, student_ref: str, *, guard_on: bool = True,
                     build_facts=None) -> list[FactFinding]:
    """Rules 9-12 for one student: for each open plan, the facts of each programme still in it. A rule that cannot run
    (see `rule_status`) produces no findings."""
    from app.os import programme_facts
    from app.os.knowledge.programmes import ProgrammeStore

    build = build_facts or (lambda ref, intake: programme_facts.build(engine, tenant_id, knowledge, books, ref, intake))
    status = rule_status(engine, tenant_id, guard_on)
    suspect = suspect_domains(engine, tenant_id) if status[12] is None else None
    domains, programmes = SourceDomains(engine, tenant_id), ProgrammeStore(engine, tenant_id)
    out: list[FactFinding] = []
    with engine.connect() as conn:
        plans = conn.execute(select(P.c.id, P.c.contract).where(
            P.c.tenant_id == tenant_id, P.c.student_ref == student_ref, P.c.status.in_(PLAN_OPEN)).order_by(P.c.id)).all()
    for plan in plans:
        contract: Mapping = plan.contract
        intake = IntakeRef.model_validate(contract["target_intake"])
        cancelled = OverrideStore(engine, tenant_id).cancelled(plan.id)
        codes: dict[int, set[str]] = {r: set() for r in RULES}
        for p in contract.get("programmes") or []:
            ref = p["programme_ref"]
            if ref in cancelled:
                continue
            shown: ProgrammeFactsV1 | None = build(ref, intake)
            programme = programmes.get(ref)
            if shown is None or programme is None:
                continue
            scope = Scope(region=programme.region or "", family=programme.family or "", route_key=programme.route_key)
            own = own_domains(engine, tenant_id, ref)

            def listed(url: str, scope=scope, own=own) -> bool:
                host = urlsplit(url).hostname or ""
                return domain_of(url) in own or domains.is_listed(host, scope)

            raw = knowledge.programme_facts([ref], [e.field for e in shown.facts], intake.year, intake_term=intake.term,
                                            fallback_previous=True)
            urls = {field: f.url for (_, field), f in raw.items() if f.url}
            for rule, found in check_entries(shown.facts, intake, listed if status[9] is None else None, suspect,
                                             urls).items():
                codes[rule] |= set(found)
        out += [FactFinding(rule, tuple(sorted(c)), plan.id) for rule, c in codes.items() if c]
    return out
