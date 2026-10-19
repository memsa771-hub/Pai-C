"""SQL-backed Knowledge store (os_knowledge_facts). Slice 2's research agent writes through the same API."""

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import models
from app.os.knowledge.port import Fact

T = models.knowledge_facts
Scope = Literal["route", "programme"]


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

    def upsert(self, scope: Scope, ref: str, field: str, fact: Fact) -> int:
        values = {
            "value": fact.value, "quote": fact.quote, "url": fact.url, "checked_at": fact.checked_at,
            "status": fact.status, "conflict_note": fact.conflict_note,
        }
        stmt = insert(T).values(
            tenant_id=self.tenant_id, scope=scope, ref=ref, field=field, intake_year=fact.intake_year, **values
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_os_knowledge_facts", set_={**values, "updated_at": func.now()}
        ).returning(T.c.id)
        with self.engine.begin() as conn:
            return conn.execute(stmt).scalar_one()

    def get(self, fact_id: int) -> tuple[Scope, str, str, Fact]:
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)).first()
        if row is None:
            raise KeyError(fact_id)
        return row.scope, row.ref, row.field, _fact(row)

    def confirm(self, fact_id: int, *, value, quote: str, url: str, status: str,
                conflict_note: str | None = None) -> Fact:
        _, _, _, old = self.get(fact_id)
        new = Fact(value=value, quote=quote, url=url, checked_at=old.checked_at, intake_year=old.intake_year,
                   status=status, conflict_note=conflict_note, id=fact_id)  # validates the trust rule
        with self.engine.begin() as conn:
            conn.execute(update(T).where(T.c.id == fact_id).values(
                value=value, quote=quote, url=url, status=status, conflict_note=conflict_note,
                checked_at=func.now(), updated_at=func.now(),
            ))
        return new
