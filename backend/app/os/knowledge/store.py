"""SQL-backed Knowledge store (os_knowledge_facts). Slice 2's research agent writes through the same API."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Engine, and_, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert

from app.os import clock, models
from app.os.knowledge.port import Fact

T = models.knowledge_facts
RV = models.fact_revisions
Scope = Literal["route", "programme"]
Source = Literal["seed", "manual", "research"]
# P2-D9: what a revision records of a fact (its key columns never change, so they are not repeated)
_TRACKED = ("value", "quote", "url", "checked_at", "status", "conflict_note", "source", "fact_class", "read_method",
            "language")


def _fact(row) -> Fact:
    return Fact(
        value=row.value, quote=row.quote, url=row.url, checked_at=row.checked_at,
        intake_year=row.intake_year, status=row.status, conflict_note=row.conflict_note, id=row.id,
        intake_term=row.intake_term, owner_ref=row.owner_ref, fact_class=row.fact_class,
        read_method=row.read_method, language=row.language,
    )


@dataclass(frozen=True)
class Revision:
    id: int
    fact_id: int
    action: str
    before: dict | None
    after: dict
    cause: str
    cause_ref: str | None
    actor: str | None
    at: datetime


def _snapshot(row) -> dict[str, Any]:
    out = {k: getattr(row, k) for k in _TRACKED}
    out["checked_at"] = out["checked_at"].isoformat() if out["checked_at"] is not None else None
    return out


def _revise(conn, tenant_id: str, fact_id: int, before, after, cause: str, cause_ref: str | None,
            actor: str | None) -> None:
    """Writes one append-only revision; no revision when nothing tracked changed."""
    if cause not in models.REVISION_CAUSES:
        raise ValueError(f"unknown revision cause '{cause}'")
    old = _snapshot(before) if before is not None else None
    new = _snapshot(after)
    if old == new:
        return
    if old is None:
        action = "insert"
    elif {k for k in _TRACKED if old[k] != new[k]} == {"status"}:
        action = "status"
    else:
        action = "change"
    conn.execute(RV.insert().values(tenant_id=tenant_id, fact_id=fact_id, action=action, before=old, after=new,
                                    cause=cause, cause_ref=cause_ref, actor=actor))


class SqlKnowledge:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def _select(self, scope: Scope, refs: Sequence[str], fields: Sequence[str], intake_year: int,
                intake_term: str | None, owner_ref: str, fallback_previous: bool = False):
        # P2-D24: with the fallback an earlier year's row is also read; the newest year then the newest id wins, so a
        # row of the asked year always beats an older one, and a later year is never read. An earlier year's row must
        # be of the asked term; a row of the asked year whose term was never recorded ('') counts for any term, because
        # the write paths of before P2 do not record one.
        if fallback_previous:
            this_year = and_(T.c.intake_year == intake_year, T.c.intake_term.in_([intake_term, ""])
                             if intake_term is not None else true())
            earlier = and_(T.c.intake_year < intake_year, T.c.intake_term == intake_term
                           if intake_term is not None else true())
            year = or_(this_year, earlier)
        else:
            year = T.c.intake_year == intake_year
        q = select(T).where(
            T.c.tenant_id == self.tenant_id, T.c.scope == scope, T.c.ref.in_(list(refs)),
            T.c.field.in_(list(fields)), year, T.c.owner_ref == owner_ref,
        )
        if intake_term is not None and not fallback_previous:
            q = q.where(T.c.intake_term == intake_term)
        return q.order_by(T.c.intake_year, T.c.id)  # intake_term=None matches every term; on a clash the newest row wins

    def programme_facts(
        self, refs: Sequence[str], fields: Sequence[str], intake_year: int, *,
        intake_term: str | None = None, owner_ref: str = "", fallback_previous: bool = False,
    ) -> dict[tuple[str, str], Fact]:
        if not refs or not fields:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(self._select("programme", refs, fields, intake_year, intake_term, owner_ref,
                                                 fallback_previous)).all()
        return {(r.ref, r.field): _fact(r) for r in rows}

    def route_facts(self, route_key: str, fields: Sequence[str], intake_year: int, *,
                    intake_term: str | None = None, owner_ref: str = "",
                    fallback_previous: bool = False) -> dict[str, Fact]:
        if not fields:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(self._select("route", [route_key], fields, intake_year, intake_term, owner_ref,
                                                 fallback_previous)).all()
        return {r.field: _fact(r) for r in rows}

    def _row(self, conn, fact_id: int, lock: bool = False):
        q = select(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)
        return conn.execute(q.with_for_update() if lock else q).first()

    def _keyed(self, conn, scope: str, ref: str, field: str, fact: Fact):
        return conn.execute(select(T).where(
            T.c.tenant_id == self.tenant_id, T.c.scope == scope, T.c.ref == ref, T.c.field == field,
            T.c.intake_term == fact.intake_term, T.c.intake_year == fact.intake_year, T.c.owner_ref == fact.owner_ref,
        ).with_for_update()).first()

    def revisions(self, fact_id: int) -> list[Revision]:
        """The fact's history, oldest first (P2-D9). Append only: the store has no way to edit or delete one."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(RV).where(RV.c.tenant_id == self.tenant_id, RV.c.fact_id == fact_id)
                                .order_by(RV.c.id)).all()
        return [Revision(r.id, r.fact_id, r.action, r.before, r.after, r.cause, r.cause_ref, r.actor, r.at)
                for r in rows]

    def _values(self, fact: Fact, source: Source) -> dict:
        if source not in models.FACT_SOURCES:
            raise ValueError(f"unknown fact source '{source}'")
        return {
            "value": fact.value, "quote": fact.quote, "url": fact.url, "checked_at": fact.checked_at,
            "status": fact.status, "conflict_note": fact.conflict_note, "source": source,
            "fact_class": fact.fact_class, "read_method": fact.read_method, "language": fact.language,
        }

    def _key(self, scope: str, ref: str, field: str, fact: Fact) -> dict:
        return {"tenant_id": self.tenant_id, "scope": scope, "ref": ref, "field": field,
                "intake_term": fact.intake_term, "intake_year": fact.intake_year, "owner_ref": fact.owner_ref}

    def upsert(self, scope: Scope, ref: str, field: str, fact: Fact, source: Source = "manual",
               research_run_id: int | None = None, evidence: list | None = None, *,
               cause: str | None = None, cause_ref: str | None = None, actor: str | None = None) -> int:
        """Adds or replaces a fact. An admin's fact is `manual` (the default); research passes `research`,
        its run and the evidence of every reading (Slice 2 spec §4.4). Each change is a revision (P2-D9)."""
        values = {**self._values(fact, source), "research_run_id": research_run_id, "evidence": evidence}
        stmt = insert(T).values(**self._key(scope, ref, field, fact), **values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_os_knowledge_facts", set_={**values, "updated_at": func.now()}
        ).returning(T.c.id)
        with self.engine.begin() as conn:
            before = self._keyed(conn, scope, ref, field, fact)
            fact_id = conn.execute(stmt).scalar_one()
            _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), cause or source, cause_ref, actor)
            return fact_id

    def insert_if_absent(self, scope: Scope, ref: str, field: str, fact: Fact, source: Source = "seed", *,
                         cause: str | None = None, cause_ref: str | None = None, actor: str | None = None) -> None:
        """Adds a fact only if its key is new: re-seeding never overwrites a confirmed or researched fact (M6)."""
        stmt = insert(T).values(
            **self._key(scope, ref, field, fact), **self._values(fact, source),
        ).on_conflict_do_nothing(constraint="uq_os_knowledge_facts").returning(T.c.id)
        with self.engine.begin() as conn:
            fact_id = conn.execute(stmt).scalar()
            if fact_id is not None:
                _revise(conn, self.tenant_id, fact_id, None, self._row(conn, fact_id), cause or source, cause_ref,
                        actor)

    def get(self, fact_id: int) -> tuple[Scope, str, str, Fact]:
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)).first()
        if row is None:
            raise KeyError(fact_id)
        return row.scope, row.ref, row.field, _fact(row)

    def mark_stale(self, fact_id: int) -> bool:
        """A confirmed fact becomes stale (spec §4.7). False if it was no longer confirmed."""
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            r = conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id,
                                             T.c.status == "confirmed")
                             .values(status="stale", updated_at=func.now()).returning(T.c.id))
            if r.first() is None:
                return False
            _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), "monitor", None, "freshness")
            return True

    def set_status(self, fact_id: int, status: str, *, cause: str, cause_ref: str | None = None,
                   actor: str | None = None) -> Fact:
        """Moves a fact to another trust level with its cause (P2-D6, D9). The trust rule is checked first:
        `confirmed` and `verified` need a quote and URL. T5 decides who may set `verified`."""
        _, _, _, old = self.get(fact_id)
        Fact(**{**old.__dict__, "status": status})  # validates
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)
                         .values(status=status, updated_at=func.now()))
            after = self._row(conn, fact_id)
            _revise(conn, self.tenant_id, fact_id, before, after, cause, cause_ref, actor)
        return _fact(after)

    def annotate(self, fact_id: int, *, conflict_note: str | None, checked_at=None) -> None:
        """Research found the same value again (`checked_at`), or a different one (`conflict_note`), for a
        confirmed fact: the value, quote and status stay (spec §4.6 step 6)."""
        values: dict = {"conflict_note": conflict_note, "updated_at": func.now()}
        if checked_at is not None:
            values["checked_at"] = checked_at
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id).values(**values))
            if before is not None:
                _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), "research", None, None)

    def confirm(self, fact_id: int, *, value, quote: str, url: str, status: str,
                conflict_note: str | None = None) -> Fact:
        _, _, _, old = self.get(fact_id)
        new = Fact(value=value, quote=quote, url=url, checked_at=old.checked_at, intake_year=old.intake_year,
                   status=status, conflict_note=conflict_note, id=fact_id, intake_term=old.intake_term,
                   owner_ref=old.owner_ref, fact_class=old.fact_class, read_method=old.read_method,
                   language=old.language)  # validates the trust rule
        stamp = clock.now()  # the shared clock: freshness compares checked_at with it
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            conn.execute(update(T).where(T.c.id == fact_id).values(
                value=value, quote=quote, url=url, status=status, conflict_note=conflict_note,
                checked_at=stamp, updated_at=stamp, source="manual",
            ))
            _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), "manual", None, "admin")
        return new
