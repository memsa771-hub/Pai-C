"""SQL-backed Knowledge store (os_knowledge_facts). Slice 2's research agent writes through the same API."""

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import clock, models
from app.os.knowledge.port import Fact

T = models.knowledge_facts
Scope = Literal["route", "programme"]
Source = Literal["seed", "manual", "research"]


def _fact(row) -> Fact:
    return Fact(
        value=row.value, quote=row.quote, url=row.url, checked_at=row.checked_at,
        intake_year=row.intake_year, status=row.status, conflict_note=row.conflict_note, id=row.id,
    )


class SqlKnowledge:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def _select(self, scope: Scope, refs: Sequence[str], fields: Sequence[str], intake_year: int):
        return select(T).where(
            T.c.tenant_id == self.tenant_id, T.c.scope == scope, T.c.ref.in_(list(refs)),
            T.c.field.in_(list(fields)), T.c.intake_year == intake_year,
        )

    def programme_facts(
        self, refs: Sequence[str], fields: Sequence[str], intake_year: int
    ) -> dict[tuple[str, str], Fact]:
        if not refs or not fields:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(self._select("programme", refs, fields, intake_year)).all()
        return {(r.ref, r.field): _fact(r) for r in rows}

    def route_facts(self, route_key: str, fields: Sequence[str], intake_year: int) -> dict[str, Fact]:
        if not fields:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(self._select("route", [route_key], fields, intake_year)).all()
        return {r.field: _fact(r) for r in rows}

    def _values(self, fact: Fact, source: Source) -> dict:
        if source not in models.FACT_SOURCES:
            raise ValueError(f"unknown fact source '{source}'")
        return {
            "value": fact.value, "quote": fact.quote, "url": fact.url, "checked_at": fact.checked_at,
            "status": fact.status, "conflict_note": fact.conflict_note, "source": source,
        }

    def upsert(self, scope: Scope, ref: str, field: str, fact: Fact, source: Source = "manual",
               research_run_id: int | None = None, evidence: list | None = None) -> int:
        """Adds or replaces a fact. An admin's fact is `manual` (the default); research passes `research`,
        its run and the evidence of every reading (Slice 2 spec §4.4)."""
        values = {**self._values(fact, source), "research_run_id": research_run_id, "evidence": evidence}
        stmt = insert(T).values(
            tenant_id=self.tenant_id, scope=scope, ref=ref, field=field, intake_year=fact.intake_year, **values
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_os_knowledge_facts", set_={**values, "updated_at": func.now()}
        ).returning(T.c.id)
        with self.engine.begin() as conn:
            return conn.execute(stmt).scalar_one()

    def insert_if_absent(self, scope: Scope, ref: str, field: str, fact: Fact, source: Source = "seed") -> None:
        """Adds a fact only if its key is new: re-seeding never overwrites a confirmed or researched fact (M6)."""
        stmt = insert(T).values(
            tenant_id=self.tenant_id, scope=scope, ref=ref, field=field, intake_year=fact.intake_year,
            **self._values(fact, source),
        ).on_conflict_do_nothing(constraint="uq_os_knowledge_facts")
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def get(self, fact_id: int) -> tuple[Scope, str, str, Fact]:
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)).first()
        if row is None:
            raise KeyError(fact_id)
        return row.scope, row.ref, row.field, _fact(row)

    def mark_stale(self, fact_id: int) -> bool:
        """A confirmed fact becomes stale (spec §4.7). False if it was no longer confirmed."""
        with self.engine.begin() as conn:
            r = conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id,
                                             T.c.status == "confirmed")
                             .values(status="stale", updated_at=func.now()).returning(T.c.id))
            return r.first() is not None

    def annotate(self, fact_id: int, *, conflict_note: str | None, checked_at=None) -> None:
        """Research found the same value again (`checked_at`), or a different one (`conflict_note`), for a
        confirmed fact: the value, quote and status stay (spec §4.6 step 6)."""
        values: dict = {"conflict_note": conflict_note, "updated_at": func.now()}
        if checked_at is not None:
            values["checked_at"] = checked_at
        with self.engine.begin() as conn:
            conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id).values(**values))

    def confirm(self, fact_id: int, *, value, quote: str, url: str, status: str,
                conflict_note: str | None = None) -> Fact:
        _, _, _, old = self.get(fact_id)
        new = Fact(value=value, quote=quote, url=url, checked_at=old.checked_at, intake_year=old.intake_year,
                   status=status, conflict_note=conflict_note, id=fact_id)  # validates the trust rule
        stamp = clock.now()  # the shared clock: freshness compares checked_at with it
        with self.engine.begin() as conn:
            conn.execute(update(T).where(T.c.id == fact_id).values(
                value=value, quote=quote, url=url, status=status, conflict_note=conflict_note,
                checked_at=stamp, updated_at=stamp, source="manual",
            ))
        return new
