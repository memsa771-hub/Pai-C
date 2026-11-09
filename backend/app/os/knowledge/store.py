"""SQL-backed Knowledge store (os_knowledge_facts). Slice 2's research agent writes through the same API."""

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import clock, models
from app.os.knowledge.port import CONFIRMED_LEVELS, Fact

T = models.knowledge_facts
RV = models.fact_revisions
RI = models.review_items
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


class StaleFact(ValueError):
    """The fact changed between the moment a decision was made on it and the moment it was written (P2-T5, I2)."""


# What a reviewer judges: the reading itself and how it was read (P2-T5, I4). A change to any of them voids reviews.
_CONTENT = ("value", "quote", "url", "fact_class", "read_method")


def fact_digest(fact: "Fact") -> str:
    """sha256 of the content a reviewer sees. `set_status` and `revise` can require it on the locked row."""
    return hashlib.sha256(json.dumps([getattr(fact, k) for k in _CONTENT], sort_keys=True, default=str)
                          .encode()).hexdigest()


def _check_digest(row, expected: str | None) -> None:
    if expected is not None and fact_digest(_fact(row)) != expected:
        raise StaleFact("the fact changed since it was read; nothing was written")


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
            actor: str | None, except_item: int | None = None) -> None:
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
    if old is not None and any(old[k] != new[k] for k in _CONTENT):
        _void_reviews(conn, tenant_id, fact_id, except_item, after)


def _void_reviews(conn, tenant_id: str, fact_id: int, except_item: int | None, after) -> None:
    """A fact whose reading changed leaves no open verify item: its checks were of another reading (I3). Items a
    reviewer holds locked right now are skipped (no waiting, so no deadlock); their checks carry a digest and are
    voided when they are applied, or by the queue's sweep. A fact that can still be checked gets a fresh verify item in
    the same transaction (the author of the old item stays barred from checking the new reading)."""
    from app.os.knowledge.review.policy import load_policy

    q = select(RI.c.id).where(RI.c.tenant_id == tenant_id, RI.c.fact_id == fact_id, RI.c.kind == "verify",
                              RI.c.status == "open")
    if except_item is not None:
        q = q.where(RI.c.id != except_item)
    voided = conn.execute(update(RI).where(RI.c.id.in_(q.with_for_update(skip_locked=True)))
                          .values(status="closed", resolution="void", closed_at=func.now())
                          .returning(RI.c.batch_ref, RI.c.payload)).all()
    checkable = after.status == "confirmed" or (
        after.status == "unconfirmed" and after.read_method in load_policy().compare_with_original)
    if voided and checkable:
        old = voided[0]
        author = (old.payload or {}).get("author_ref")
        conn.execute(RI.insert().values(
            tenant_id=tenant_id, kind="verify", fact_id=fact_id, subject="", field=after.field,
            intake_term=after.intake_term, intake_year=after.intake_year, owner_ref=after.owner_ref,
            payload={"author_ref": author} if author else {}, batch_ref=old.batch_ref,
            dedupe_key=f"verify:{fact_id}", opened_by="review"))


class SqlKnowledge:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def _select(self, scope: Scope, refs: Sequence[str], fields: Sequence[str], intake_year: int,
                intake_term: str | None, owner_ref: str | None):
        q = select(T).where(
            T.c.tenant_id == self.tenant_id, T.c.scope == scope, T.c.ref.in_(list(refs)),
            T.c.field.in_(list(fields)), T.c.intake_year == intake_year,
        )
        if intake_term is not None:
            q = q.where(T.c.intake_term == intake_term)
        if owner_ref is not None:
            q = q.where(T.c.owner_ref.in_(sorted({owner_ref, ""})))
        return q.order_by(T.c.id)

    @staticmethod
    def _resolve(rows, owner_ref: str | None, key) -> dict:
        """One row per key (P2-D8, plan "Resolution order"):
        - owner: with an owner_ref, that owner's row wins over the general ('') row; with None (any owner), the
          general row wins, then the newest id;
        - term: with intake_term=None, the newest id wins among terms (T8 will prefer the intake's current term)."""
        best: dict = {}
        for r in rows:  # ordered by id, so a later row of equal rank replaces an earlier one
            rank = (r.owner_ref == owner_ref) if owner_ref else (r.owner_ref == "")
            k = key(r)
            if k not in best or rank >= best[k][0]:
                best[k] = (rank, r)
        return {k: _fact(r) for k, (_, r) in best.items()}

    def programme_facts(
        self, refs: Sequence[str], fields: Sequence[str], intake_year: int, *,
        intake_term: str | None = None, owner_ref: str | None = None,
    ) -> dict[tuple[str, str], Fact]:
        if not refs or not fields:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(self._select("programme", refs, fields, intake_year, intake_term, owner_ref)).all()
        return self._resolve(rows, owner_ref, lambda r: (r.ref, r.field))

    def route_facts(self, route_key: str, fields: Sequence[str], intake_year: int, *,
                    intake_term: str | None = None, owner_ref: str | None = None) -> dict[str, Fact]:
        if not fields:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(self._select("route", [route_key], fields, intake_year, intake_term, owner_ref)).all()
        return self._resolve(rows, owner_ref, lambda r: r.field)

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

    @staticmethod
    def _no_verified(status: str) -> None:
        if status == "verified":
            raise ValueError("verified is reached only through review: set_status(..., cause='review')")

    def upsert(self, scope: Scope, ref: str, field: str, fact: Fact, source: Source = "manual",
               research_run_id: int | None = None, evidence: list | None = None, *,
               cause: str | None = None, cause_ref: str | None = None, actor: str | None = None) -> int:
        """Adds or replaces a fact. An admin's fact is `manual` (the default); research passes `research`,
        its run and the evidence of every reading (Slice 2 spec §4.4). Each change is a revision (P2-D9).
        A write onto a `verified` row keeps `verified` when value and quote are the same; otherwise the row drops
        to `unconfirmed` and goes back to review (the revision records the cause and before/after)."""
        self._no_verified(fact.status)
        values = {**self._values(fact, source), "research_run_id": research_run_id, "evidence": evidence}
        with self.engine.begin() as conn:
            before = self._keyed(conn, scope, ref, field, fact)
            if before is None:  # a concurrent first insert loses the race here and is re-read as an update
                fact_id = conn.execute(insert(T).values(**self._key(scope, ref, field, fact), **values)
                                       .on_conflict_do_nothing(constraint="uq_os_knowledge_facts")
                                       .returning(T.c.id)).scalar()
                if fact_id is None:
                    before = self._keyed(conn, scope, ref, field, fact)
            if before is not None:
                fact_id = before.id
                if before.status == "verified":
                    same = before.value == fact.value and before.quote == fact.quote
                    values["status"] = "verified" if same else "unconfirmed"
                conn.execute(update(T).where(T.c.id == fact_id).values(**values, updated_at=func.now()))
            _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), cause or source, cause_ref, actor)
            return fact_id

    def insert_if_absent(self, scope: Scope, ref: str, field: str, fact: Fact, source: Source = "seed", *,
                         cause: str | None = None, cause_ref: str | None = None, actor: str | None = None) -> None:
        """Adds a fact only if its key is new: re-seeding never overwrites a confirmed or researched fact (M6)."""
        self._no_verified(fact.status)
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
        """A confirmed or verified fact becomes stale (spec §4.7). False if it was neither any more."""
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            r = conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id,
                                             T.c.status.in_(("confirmed", "verified")))
                             .values(status="stale", updated_at=func.now()).returning(T.c.id))
            if r.first() is None:
                return False
            _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), "monitor", None, "freshness")
            return True

    @contextmanager
    def _tx(self, conn) -> Iterator[Any]:
        """The caller's transaction when it passes one (so several writes are one commit), else a new one."""
        if conn is not None:
            yield conn
        else:
            with self.engine.begin() as own:
                yield own

    def locked(self, conn, fact_id: int) -> tuple[str, str, str, Fact]:
        """(scope, ref, field, fact) as it is now, locked for this transaction."""
        row = self._row(conn, fact_id, lock=True)
        if row is None:
            raise KeyError(fact_id)
        return row.scope, row.ref, row.field, _fact(row)

    def set_status(self, fact_id: int, status: str, *, cause: str, cause_ref: str | None = None,
                   actor: str | None = None, expected_digest: str | None = None, conn=None) -> Fact:
        """Moves a fact to another trust level with its cause (P2-D6, D9). The trust rule is checked on the locked
        row: `confirmed` and `verified` need a quote and URL, and `verified` needs cause `review`. With
        `expected_digest` the write is refused (StaleFact) if the locked row's reading is not the one decided on."""
        if status == "verified" and cause != "review":
            raise ValueError("verified is reached only with cause 'review'")
        with self._tx(conn) as c:
            before = self._row(c, fact_id, lock=True)
            if before is None:
                raise KeyError(fact_id)
            _check_digest(before, expected_digest)
            Fact(**{**_fact(before).__dict__, "status": status})  # validates
            c.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)
                      .values(status=status, updated_at=func.now()))
            after = self._row(c, fact_id)
            _revise(c, self.tenant_id, fact_id, before, after, cause, cause_ref, actor)
        return _fact(after)

    _REVISABLE = ("value", "quote", "url", "status", "conflict_note", "read_method", "language")

    def revise(self, fact_id: int, *, cause: str, cause_ref: str | None = None, actor: str | None = None,
               expected_digest: str | None = None, except_item: int | None = None, conn=None,
               **changes: Any) -> Fact:
        """Changes some columns of a fact in one step, with its cause (P2-D9). Used by the review queue (T5) to
        correct a value or move a fact down. Everything is read and checked on the locked row; a new value, quote or
        URL sets `checked_at` to the shared clock. `expected_digest` refuses the write on a changed reading;
        `except_item` is the review item the caller is itself closing. Nothing is deleted: the old state stays in
        the revision."""
        bad = sorted(set(changes) - set(self._REVISABLE))
        if bad:
            raise ValueError(f"cannot revise {bad}")
        self._no_verified(changes.get("status"))
        with self._tx(conn) as c:
            before = self._row(c, fact_id, lock=True)
            if before is None:
                raise KeyError(fact_id)
            _check_digest(before, expected_digest)
            old = _fact(before)
            if old.status == "verified" and {"value", "quote", "url"} & set(changes) and "status" not in changes:
                changes = {**changes, "status": "unconfirmed"}  # a changed reading is no longer verified (T1 rule)
            Fact(**{**old.__dict__, **changes})  # validates
            values = dict(changes)
            if {"value", "quote", "url"} & set(changes):
                values["checked_at"] = clock.now()
            c.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id)
                      .values(**values, updated_at=func.now()))
            after = self._row(c, fact_id)
            _revise(c, self.tenant_id, fact_id, before, after, cause, cause_ref, actor, except_item)
        return _fact(after)

    def annotate(self, fact_id: int, *, conflict_note: str | None, checked_at=None, cause: str = "research",
                 cause_ref: str | None = None, actor: str | None = None) -> None:
        """Research found the same value again (`checked_at`), or a different one (`conflict_note`), for a
        confirmed fact: the value, quote and status stay (spec §4.6 step 6)."""
        values: dict = {"conflict_note": conflict_note, "updated_at": func.now()}
        if checked_at is not None:
            values["checked_at"] = checked_at
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id).values(**values))
            if before is not None:
                _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), cause, cause_ref, actor)

    def confirm(self, fact_id: int, *, value, quote: str, url: str, status: str,
                conflict_note: str | None = None) -> Fact:
        self._no_verified(status)
        _, _, _, old = self.get(fact_id)
        new = Fact(value=value, quote=quote, url=url, checked_at=old.checked_at, intake_year=old.intake_year,
                   status=status, conflict_note=conflict_note, id=fact_id, intake_term=old.intake_term,
                   owner_ref=old.owner_ref, fact_class=old.fact_class, read_method=old.read_method,
                   language=old.language)  # validates the trust rule
        stamp = clock.now()  # the shared clock: freshness compares checked_at with it
        with self.engine.begin() as conn:
            before = self._row(conn, fact_id, lock=True)
            conn.execute(update(T).where(T.c.id == fact_id, T.c.tenant_id == self.tenant_id).values(
                value=value, quote=quote, url=url, status=status, conflict_note=conflict_note,
                checked_at=stamp, updated_at=stamp, source="manual",
            ))
            _revise(conn, self.tenant_id, fact_id, before, self._row(conn, fact_id), "manual", None, "admin")
        return new
