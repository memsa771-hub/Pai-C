"""ProgrammeFacts (P2 spec P2-D27, §4.10; master R-23, R-26, R-48): a programme's facts for one intake, each with its
level, source, quote, checked date and intake. The level and whether a value travels come from the one display rule
(`knowledge/display.py`); a fact of another intake is read through the labelled fallback (P2-D24) and always carries
its own intake."""

from sqlalchemy import Engine, distinct, select

from app.os import models
from app.os.compiler.compile import needed_fields
from app.os.contracts.programme_facts import FactEntry, ProgrammeFactsV1, SourceRef
from app.os.contracts.route_contract import IntakeRef
from app.os.knowledge import KnowledgePort, display, merit
from app.os.knowledge.programmes import ProgrammeStore
from app.os.playbooks import newest_plain

K = models.knowledge_facts
_FLOOR = 2025  # IntakeRef's earliest year


def _fields(engine: Engine, tenant_id: str, books, programme_ref: str, route_key: str, year: int) -> list[str]:
    book = newest_plain(books.values()).get(route_key)
    names = set(needed_fields(book)[1]) if book is not None else set()
    with engine.connect() as conn:
        names |= set(conn.execute(select(distinct(K.c.field)).where(
            K.c.tenant_id == tenant_id, K.c.scope == "programme", K.c.ref == programme_ref,
            K.c.intake_year <= year)).scalars().all())
    return sorted(names)


def build(engine: Engine, tenant_id: str, knowledge: KnowledgePort, books, programme_ref: str,
          intake: IntakeRef) -> ProgrammeFactsV1 | None:
    """None when the programme is unknown."""
    programme = ProgrammeStore(engine, tenant_id).get(programme_ref)
    if programme is None:
        return None
    fields = _fields(engine, tenant_id, books, programme_ref, programme.route_key, intake.year)
    found = knowledge.programme_facts([programme_ref], fields, intake.year, intake_term=intake.term,
                                      fallback_previous=True)
    # rows whose term was never recorded count for the asked year (the strict-term read leaves them out)
    for key, fact in knowledge.programme_facts([programme_ref], fields, intake.year, fallback_previous=True).items():
        if key not in found and fact.intake_term == "":
            found[key] = fact
    entries = []
    for field in fields:
        fact = found.get((programme_ref, field))
        if fact is not None and fact.intake_year < _FLOOR:
            fact = None  # older than a labelled intake can be
        shown = display(fact, field, intake_year=intake.year, intake_term=intake.term)
        high = shown.high_stakes
        cls = shown.fact_class
        if cls == "unclassified" and (kind := merit.is_merit_field(field)):  # `merit_formula_<category>` etc.
            cls = merit.formula_field() if kind == "formula" else merit.closing_field()
        if fact is None:
            entries.append(FactEntry(field=field, fact_class=cls, high_stakes=high, level="missing"))
            continue
        source = (SourceRef(url=fact.url, quote=fact.quote, checked_at=fact.checked_at)
                  if fact.url and fact.quote else None)
        entries.append(FactEntry(
            field=field, fact_class=cls, high_stakes=high, level=shown.level,
            value=fact.value if shown.show_value else None, source=source,
            fact_intake=IntakeRef(term=fact.intake_term or intake.term, year=fact.intake_year),
            other_intake=shown.other_intake, owner_ref=fact.owner_ref or None, read_method=fact.read_method,
            language=fact.language))
    return ProgrammeFactsV1(programme_ref=programme_ref, route_key=programme.route_key, intake=intake, facts=entries)
