"""Consistency rules 9-12 of master §9.3 (P2-T12, R-05, R-24, R-25, R-26, R-71): what a student is shown.

Each rule reads what the screens would show for the programmes in the student's open plans, in the form the ProgrammeFacts
port gives them (`programme_facts.build`: the one display rule and the labelled-year rule are applied there), and finds the
facts that break a rule:

    9.  a fact shown with a value whose source domain is not on the allow-list (or a programme's or body's own official
        domain);
    10. a high-stakes fact shown as fact unless it is `verified`;
    11. a fact of another intake shown without its year;
    12. a fact shown whose source domain is marked `suspect` (R-71).

A finding carries a rule number and codes `<code>:<field>`, never a value (R-01). The check reads only; the host job opens
the cases. Zero findings is the expected state: a finding means a surface bypassed the display rule or the source rules."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import Engine, select

from app.os import models
from app.os.contracts.programme_facts import FactEntry, ProgrammeFactsV1
from app.os.contracts.route_contract import IntakeRef
from app.os.kernel.states import PLAN_OPEN
from app.os.knowledge.research.links import domain_of
from app.os.replan.store import OverrideStore

RULES = (9, 10, 11, 12)
P, SD, PG, RG = models.plans, models.source_domains, models.programmes, models.registry


@dataclass(frozen=True)
class FactFinding:
    rule: int
    codes: tuple[str, ...]
    plan_id: int | None = None


def allowed_domains(engine: Engine, tenant_id: str) -> tuple[set[str] | None, set[str]]:
    """(domains a shown fact may come from, domains marked suspect). Allowed: the reviewed allow-list's active entries,
    every programme's own official domains, and the official domains of registry entries. The first is None while no
    reviewed allow-list is loaded (the guard is off or nothing is listed yet): there is then nothing to check against, and
    rule 9 stays silent rather than flag every source."""
    with engine.connect() as conn:
        entries = conn.execute(select(SD.c.domain, SD.c.state, SD.c.tier).where(SD.c.tenant_id == tenant_id)).all()
        programmes = conn.execute(select(PG.c.official_domains).where(PG.c.tenant_id == tenant_id)).scalars().all()
        registry = conn.execute(select(RG.c.official_domains).where(RG.c.tenant_id == tenant_id)).scalars().all()
    suspect = {domain_of(f"https://{e.domain}/") for e in entries if e.state == "suspect"}
    allowed = {domain_of(f"https://{e.domain}/") for e in entries if e.state == "active" and e.tier is not None}
    for domains in (*programmes, *registry):
        allowed |= {domain_of(f"https://{d}/") for d in (domains or [])}
    return (allowed - suspect if any(e.state == "active" and e.tier is not None for e in entries) else None), suspect


def check_entries(entries: Iterable[FactEntry], intake: IntakeRef, allowed: set[str] | None,
                  suspect: set[str]) -> dict[int, list[str]]:
    """The codes found per rule for the facts a student is shown. Only entries that carry a value are 'shown'."""
    found: dict[int, list[str]] = {r: [] for r in RULES}
    for e in entries:
        if e.value is None:
            continue
        host = domain_of(e.source.url) if e.source is not None else ""
        if host in suspect:
            found[12].append(f"suspect_domain:{e.field}")
        elif e.source is not None and allowed is not None and host not in allowed:
            found[9].append(f"domain_not_listed:{e.field}")
        if e.high_stakes and e.level != "verified":
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


def student_findings(engine: Engine, tenant_id: str, knowledge, books, student_ref: str,
                     build_facts=None) -> list[FactFinding]:
    """Rules 9-12 for one student: for each open plan, the facts of each programme still in it."""
    from app.os import programme_facts

    build = build_facts or (lambda ref, intake: programme_facts.build(engine, tenant_id, knowledge, books, ref, intake))
    allowed, suspect = allowed_domains(engine, tenant_id)
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
            if p["programme_ref"] in cancelled:
                continue
            shown: ProgrammeFactsV1 | None = build(p["programme_ref"], intake)
            if shown is None:
                continue
            for rule, found in check_entries(shown.facts, intake, allowed, suspect).items():
                codes[rule] |= set(found)
        out += [FactFinding(rule, tuple(sorted(c)), plan.id) for rule, c in codes.items() if c]
    return out
