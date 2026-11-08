"""SQL store of the registry (P2 spec §4.1). `record` is the one way a registry row is written (the registry's
`knowledge.record()`): it checks the rules of an entry against the rows it points to, writes the row and one append-only
revision. There is no delete: a closed or merged entity keeps its row (R-60)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import models
from app.os.registry.model import (
    ALLOWED_PARENTS, ALLOWED_SUCCESSORS, CAUSES_OF_INSTITUTIONS, NAMES_A_LIST, NATIONAL, RegistryEntry, known_region)

T = models.registry
RV = models.registry_revisions
LK = models.registry_links
PG = models.programmes
_PROGRAMME_COLUMNS = ("institution_id", "campus_id", "level", "field", "family", "region")
_UNSET: Any = object()  # a column the caller left out of link_programme: it keeps its value
_TRACKED = ("kind", "parent_id", "region", "institution_type", "name", "aliases", "official_domains", "status",
            "successor_id", "list_ids", "source_url", "quote", "checked_at", "attrs")
# which kinds each link may join (the link's `to_kind` "programme" is checked against os_programmes instead)
_LINK_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "uses_test": (("admission_system",), ("entry_test",)),
    "has_category": (("admission_system",), ("seat_category",)),
    "admits": (("admission_system",), ("institution", "campus")),
}


class RegistryError(ValueError):
    """A registry rule is broken: a missing parent or list, a wrong kind, a bad link."""


@dataclass(frozen=True)
class Recorded:
    id: int
    action: str  # insert | change | status | unchanged


@dataclass(frozen=True)
class Link:
    from_id: str
    rel: str
    to_kind: str
    to_id: str


@dataclass(frozen=True)
class RegistryRevision:
    id: int
    entity_id: str
    action: str
    before: dict | None
    after: dict
    cause: str
    cause_ref: str | None
    actor: str | None
    at: datetime
    kind: str = "entity"  # entity | link | programme: what the revision is about
    subject: str | None = None  # link: 'rel:to_kind:to_id'; programme: its ref


@dataclass(frozen=True)
class ListProgress:
    """How much of an official list is in the registry (R-35a): loaded against the count as published."""

    list_id: str
    name: str
    region: str | None
    published: int | None  # None: the page states no usable count (conflict, not readable)
    loaded: int
    count_confirmed: bool
    status: str | None

    @property
    def ratio(self) -> float | None:
        return None if not self.published else self.loaded / self.published

    @property
    def complete(self) -> bool:
        return self.published is not None and self.loaded == self.published

    @property
    def over(self) -> bool:
        return self.published is not None and self.loaded > self.published


def _entry(row) -> RegistryEntry:
    return RegistryEntry(
        entity_id=row.entity_id, kind=row.kind, name=row.name, source_url=row.source_url, checked_at=row.checked_at,
        quote=row.quote, parent_id=row.parent_id, region=row.region, institution_type=row.institution_type,
        aliases=tuple(row.aliases), official_domains=tuple(row.official_domains), status=row.status,
        successor_id=row.successor_id, list_ids=tuple(row.list_ids), attrs=dict(row.attrs))


def _values(e: RegistryEntry) -> dict[str, Any]:
    return {"kind": e.kind, "parent_id": e.parent_id, "region": e.region, "institution_type": e.institution_type,
            "name": e.name, "aliases": list(e.aliases), "official_domains": list(e.official_domains),
            "status": e.status, "successor_id": e.successor_id, "list_ids": list(dict.fromkeys(e.list_ids)),
            "source_url": e.source_url, "quote": e.quote, "checked_at": e.checked_at, "attrs": dict(e.attrs)}


def _snapshot(row) -> dict[str, Any]:
    out = {k: getattr(row, k) for k in _TRACKED}
    out["checked_at"] = out["checked_at"].isoformat()
    return out


class RegistryStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    # --- writing -------------------------------------------------------------------------------------------------

    def _kind_of(self, conn, entity_id: str) -> str | None:
        return conn.execute(select(T.c.kind).where(T.c.tenant_id == self.tenant_id,
                                                   T.c.entity_id == entity_id)).scalar()

    def _check_cause(self, cause: str, kind: str | None = None) -> None:
        if cause not in models.REVISION_CAUSES:
            raise ValueError(f"unknown revision cause '{cause}'")
        if kind in NAMES_A_LIST and cause not in CAUSES_OF_INSTITUTIONS:
            raise ValueError(f"cause '{cause}' cannot record a {kind}; use one of {list(CAUSES_OF_INSTITUTIONS)}")

    def _lock(self, conn, *key: str) -> None:
        """Serialises writers of one entity for the rest of the transaction, so the first insert of a row writes one
        revision and the chain of revisions has no gap. A row lock cannot do it while the row does not exist."""
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(":".join((self.tenant_id, *key)), 0))))

    def _check_refs(self, conn, e: RegistryEntry) -> None:
        if e.parent_id is not None:
            if e.parent_id == e.entity_id:
                raise RegistryError(f"{e.entity_id} cannot be its own parent")
            parent = self._kind_of(conn, e.parent_id)
            if parent is None:
                raise RegistryError(f"parent {e.parent_id} of {e.entity_id} is not in the registry")
            if parent not in ALLOWED_PARENTS[e.kind]:
                allowed = " or ".join(ALLOWED_PARENTS[e.kind]) or "nothing"
                raise RegistryError(f"the parent of a {e.kind} is {allowed}, not a {parent}")
        if e.successor_id is not None:
            if e.successor_id == e.entity_id:
                raise RegistryError(f"{e.entity_id} cannot be its own successor (itself)")
            succ = self._kind_of(conn, e.successor_id)
            if succ is None:
                raise RegistryError(f"successor {e.successor_id} of {e.entity_id} is not in the registry")
            if succ not in ALLOWED_SUCCESSORS[e.kind]:
                raise RegistryError(f"the successor of a {e.kind} is a {' or '.join(ALLOWED_SUCCESSORS[e.kind])}, "
                                    f"not a {succ}")
        for list_id in dict.fromkeys(e.list_ids):
            row = conn.execute(select(T.c.kind, T.c.region).where(T.c.tenant_id == self.tenant_id,
                                                                  T.c.entity_id == list_id)).first()
            if row is None:
                raise RegistryError(f"{e.entity_id} names {list_id}, which is not in the registry (record the list first)")
            if row.kind != "official_list":
                raise RegistryError(f"{list_id} is a {row.kind}, not an official_list")
            if row.region not in (NATIONAL, e.region):
                raise RegistryError(f"{e.entity_id} is in region {e.region}; {list_id} is a list of region "
                                    f"{row.region}, so it cannot be where it came from")

    def record(self, entry: RegistryEntry, *, cause: str, cause_ref: str | None = None,
               actor: str | None = None) -> Recorded:
        """Adds or updates a registry row with its cause (research run, import id, reviewer, ...). One revision per
        change; recording the same entry again writes nothing."""
        self._check_cause(cause, entry.kind)
        values = _values(entry)
        with self.engine.begin() as conn:
            self._lock(conn, entry.entity_id)
            self._check_refs(conn, entry)
            before = conn.execute(select(T).where(T.c.tenant_id == self.tenant_id, T.c.entity_id == entry.entity_id)
                                  .with_for_update()).first()
            stmt = insert(T).values(tenant_id=self.tenant_id, entity_id=entry.entity_id, **values)
            stmt = stmt.on_conflict_do_update(constraint="uq_os_registry_entity",
                                              set_={**values, "updated_at": func.now()}).returning(T.c.id)
            row_id = conn.execute(stmt).scalar_one()
            after = conn.execute(select(T).where(T.c.id == row_id)).one()
            new = _snapshot(after)
            old = _snapshot(before) if before is not None else None
            if old == new:
                return Recorded(row_id, "unchanged")
            if old is None:
                action = "insert"
            elif {k for k in _TRACKED if old[k] != new[k]} <= {"status", "successor_id"}:
                action = "status"
            else:
                action = "change"
            conn.execute(RV.insert().values(tenant_id=self.tenant_id, registry_id=row_id, action=action,
                                            before=old, after=new, cause=cause, cause_ref=cause_ref, actor=actor))
            return Recorded(row_id, action)

    def _revise(self, conn, registry_id: int, *, kind: str, subject: str, before: dict, after: dict, cause: str,
                cause_ref: str | None, actor: str | None) -> None:
        conn.execute(RV.insert().values(tenant_id=self.tenant_id, registry_id=registry_id, kind=kind, subject=subject,
                                        action="change", before=before, after=after, cause=cause,
                                        cause_ref=cause_ref, actor=actor))

    def _id_of(self, conn, entity_id: str) -> int:
        return conn.execute(select(T.c.id).where(T.c.tenant_id == self.tenant_id,
                                                 T.c.entity_id == entity_id)).scalar_one()

    def _link_set(self, conn, from_id: str) -> list[str]:
        rows = conn.execute(select(LK.c.rel, LK.c.to_kind, LK.c.to_id).where(
            LK.c.tenant_id == self.tenant_id, LK.c.from_id == from_id).order_by(LK.c.id))
        return [f"{r.rel}:{r.to_kind}:{r.to_id}" for r in rows]

    def link(self, from_id: str, rel: str, to_id: str, to_kind: str = "registry", *, cause: str,
             cause_ref: str | None = None, actor: str | None = None) -> None:
        """An admission system's test, seat category, or what it admits. Linking twice is harmless and writes nothing
        the second time. A new link is a revision of the system with the links it had and has (R-60)."""
        if rel not in _LINK_RULES:
            raise ValueError(f"unknown link rel '{rel}'")
        from_kinds, to_kinds = _LINK_RULES[rel]
        if to_kind not in models.REGISTRY_LINK_TO:
            raise ValueError(f"unknown link target kind '{to_kind}'")
        self._check_cause(cause)
        with self.engine.begin() as conn:
            self._lock(conn, from_id)
            kind = self._kind_of(conn, from_id)
            if kind not in from_kinds:
                raise RegistryError(f"{rel} starts at an {from_kinds[0]}; {from_id} is {kind or 'not in the registry'}")
            if to_kind == "programme":
                if rel != "admits":
                    raise RegistryError(f"{rel} points at a registry entity of kind {to_kinds[0]}")
                found = conn.execute(select(PG.c.id).where(PG.c.tenant_id == self.tenant_id,
                                                           PG.c.ref == to_id)).first()
                if found is None:
                    raise RegistryError(f"programme {to_id} does not exist")
            else:
                target = self._kind_of(conn, to_id)
                if target is None:
                    raise RegistryError(f"{to_id} does not exist in the registry")
                if target not in to_kinds:
                    raise RegistryError(f"{rel} points at {' or '.join(to_kinds)}; {to_id} is {target}")
                if target in NAMES_A_LIST:
                    self._check_cause(cause, target)
            before = self._link_set(conn, from_id)
            added = conn.execute(insert(LK).values(
                tenant_id=self.tenant_id, from_id=from_id, rel=rel, to_kind=to_kind, to_id=to_id
            ).on_conflict_do_nothing(constraint="uq_os_registry_links").returning(LK.c.id)).first()
            if added is not None:
                self._revise(conn, self._id_of(conn, from_id), kind="link", subject=f"{rel}:{to_kind}:{to_id}",
                             before={"links": before}, after={"links": self._link_set(conn, from_id)}, cause=cause,
                             cause_ref=cause_ref, actor=actor)

    def link_programme(self, ref: str, *, institution_id: str, campus_id: str | None = _UNSET,
                       level: str | None = _UNSET, field: str | None = _UNSET, family: str | None = _UNSET,
                       region: str | None = _UNSET, clear: bool = False, cause: str, cause_ref: str | None = None,
                       actor: str | None = None) -> None:
        """Places an existing programme in the registry: its institution and campus, level, field, family and region.
        A column left out keeps its value; passing None is refused unless `clear=True` (a column is never cleared by
        accident). The change is a revision of the institution (and of the one the programme leaves), with the
        programme's six columns before and after."""
        self._check_cause(cause, "institution")
        given = {"campus_id": campus_id, "level": level, "field": field, "family": family, "region": region}
        nulls = [k for k, v in given.items() if v is None]
        if nulls and not clear:
            raise RegistryError(f"{', '.join(nulls)} would be cleared; pass clear=True to clear a column")
        if region is not None and region is not _UNSET and not known_region(region):
            raise ValueError(f"unknown region '{region}' (use a code of regions.yaml)")
        with self.engine.begin() as conn:
            self._lock(conn, "programme", ref)
            old = conn.execute(select(*[PG.c[c] for c in _PROGRAMME_COLUMNS]).where(
                PG.c.tenant_id == self.tenant_id, PG.c.ref == ref).with_for_update()).first()
            if old is None:
                raise RegistryError(f"programme {ref} does not exist")
            if self._kind_of(conn, institution_id) != "institution":
                raise RegistryError(f"{institution_id} is not an institution of the registry")
            new = {"institution_id": institution_id,
                   **{k: (getattr(old, k) if v is _UNSET else v) for k, v in given.items()}}
            if new["campus_id"] is not None:
                campus = conn.execute(select(T.c.kind, T.c.parent_id).where(
                    T.c.tenant_id == self.tenant_id, T.c.entity_id == new["campus_id"])).first()
                if campus is None or campus.kind != "campus" or campus.parent_id != institution_id:
                    raise RegistryError(f"{new['campus_id']} is not a campus of {institution_id}")
            before = dict(old._mapping)
            if before == new:
                return
            conn.execute(update(PG).where(PG.c.tenant_id == self.tenant_id, PG.c.ref == ref).values(
                **new, updated_at=func.now()))
            for owner in dict.fromkeys((institution_id, before["institution_id"])):
                if owner is not None and self._kind_of(conn, owner) is not None:
                    self._revise(conn, self._id_of(conn, owner), kind="programme", subject=ref, before=before,
                                 after=new, cause=cause, cause_ref=cause_ref, actor=actor)

    # --- reading -------------------------------------------------------------------------------------------------

    def get(self, entity_id: str) -> RegistryEntry | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(T.c.tenant_id == self.tenant_id, T.c.entity_id == entity_id)).first()
        return _entry(row) if row else None

    def list(self, *, kind: str | None = None, region: str | None = None, parent_id: str | None = None,
             status: str | None = None, list_id: str | None = None, q: str | None = None, limit: int = 100,
             offset: int = 0) -> list[RegistryEntry]:
        stmt = select(T).where(T.c.tenant_id == self.tenant_id)
        if kind:
            stmt = stmt.where(T.c.kind == kind)
        if region:
            stmt = stmt.where(T.c.region == region)
        if parent_id:
            stmt = stmt.where(T.c.parent_id == parent_id)
        if status:
            stmt = stmt.where(T.c.status == status)
        if list_id:
            stmt = stmt.where(T.c.list_ids.contains([list_id]))
        if q:
            text = q.strip().lower()  # % and _ in the text are the text, not wildcards
            stmt = stmt.where(or_(func.lower(T.c.name).contains(text, autoescape=True),
                                  func.lower(T.c.entity_id).contains(text, autoescape=True)))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt.order_by(T.c.id).limit(limit).offset(offset)).all()
        return [_entry(r) for r in rows]

    def children(self, entity_id: str) -> list[RegistryEntry]:
        return self.list(parent_id=entity_id, limit=10_000)

    def _links(self, where) -> list[Link]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(LK).where(LK.c.tenant_id == self.tenant_id, where).order_by(LK.c.id)).all()
        return [Link(r.from_id, r.rel, r.to_kind, r.to_id) for r in rows]

    def links_from(self, entity_id: str, rel: str | None = None) -> list[Link]:
        return self._links((LK.c.from_id == entity_id) & ((LK.c.rel == rel) if rel else True))

    def links_to(self, to_id: str, to_kind: str = "registry") -> list[Link]:
        return self._links((LK.c.to_id == to_id) & (LK.c.to_kind == to_kind))

    def programmes_of(self, institution_id: str) -> list[str]:
        with self.engine.connect() as conn:
            return list(conn.execute(select(PG.c.ref).where(PG.c.tenant_id == self.tenant_id,
                                                            PG.c.institution_id == institution_id)
                                     .order_by(PG.c.ref)).scalars())

    def revisions(self, entity_id: str) -> list[RegistryRevision]:
        """The entity's history, oldest first. Append only: the store has no way to edit or delete one."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(RV, T.c.entity_id).join(T, T.c.id == RV.c.registry_id).where(
                RV.c.tenant_id == self.tenant_id, T.c.entity_id == entity_id).order_by(RV.c.id)).all()
        return [RegistryRevision(r.id, r.entity_id, r.action, r.before, r.after, r.cause, r.cause_ref, r.actor, r.at,
                                 r.kind, r.subject) for r in rows]

    def list_progresses(self, region: str | None = None) -> list[ListProgress]:
        """Every official list with the count loaded against the count as published (R-35a)."""
        lists = self.list(kind="official_list", region=region, limit=10_000)
        with self.engine.connect() as conn:
            loaded: dict[str, int] = {}
            rows = conn.execute(select(T.c.list_ids).where(T.c.tenant_id == self.tenant_id,
                                                           T.c.list_ids != [])).scalars()
            for ids in rows:
                for list_id in set(ids):
                    loaded[list_id] = loaded.get(list_id, 0) + 1
        return [self._progress(e, loaded.get(e.entity_id, 0)) for e in lists]

    def list_progress(self, list_id: str) -> ListProgress:
        entry = self.get(list_id)
        if entry is None or entry.kind != "official_list":
            raise KeyError(list_id)
        with self.engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(T).where(
                T.c.tenant_id == self.tenant_id, T.c.list_ids.contains([list_id]))).scalar_one()
        return self._progress(entry, n)

    @staticmethod
    def _progress(e: RegistryEntry, loaded: int) -> ListProgress:
        published = e.attrs.get("row_count")
        return ListProgress(list_id=e.entity_id, name=e.name, region=e.region,
                            published=published if isinstance(published, int) else None, loaded=loaded,
                            count_confirmed=bool(e.attrs.get("count_confirmed", False)),
                            status=e.attrs.get("status"))
