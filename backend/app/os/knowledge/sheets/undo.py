"""Undo an import by replaying the revisions it wrote, backwards (P2 spec §4.6; master R-68; P2-D9). Nothing is deleted:

- a fact the import inserted is withdrawn: status `stale`, value emptied, with a note naming the undone import;
- a fact or registry row the import changed goes back to what its first revision of the import recorded as `before`;
- a registry row the import inserted is `closed` (never deleted, R-60);
- a programme the import placed or moved in the registry gets its six registry columns back from the `programme`
  revisions (`before` of the first one of the import); a programme the import created is also `excluded`;
- a link the import added (`link` revisions) is taken away again.

Every step is a new `undo` revision, and the import is marked undone in the same transaction. If anything was changed by
someone else after the import, the undo refuses and changes nothing: it lists what moved. A revision of another import
that has itself been undone does not count as a change."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, delete, func, select, update

from app.os import models
from app.os.knowledge.sheets.importlog import ImportLog, cause_ref
from app.os.knowledge.store import _snapshot as fact_snapshot
from app.os.registry.store import _snapshot as registry_snapshot

F, FR = models.knowledge_facts, models.fact_revisions
R, RR, LK = models.registry, models.registry_revisions, models.registry_links
PG = models.programmes
_FACT_FIELDS = ("value", "quote", "url", "checked_at", "status", "conflict_note", "source", "fact_class",
                "read_method", "language")
_REGISTRY_FIELDS = ("kind", "parent_id", "region", "institution_type", "name", "aliases", "official_domains", "status",
                    "successor_id", "list_ids", "source_url", "quote", "checked_at", "attrs")
_PROGRAMME_FIELDS = ("institution_id", "campus_id", "level", "field", "family", "region")


class UndoRefused(RuntimeError):
    def __init__(self, conflicts: list[str]) -> None:
        super().__init__("undo refused: changed after the import: " + ", ".join(conflicts))
        self.conflicts = conflicts


@dataclass
class UndoResult:
    facts: int = 0
    registry: int = 0
    programmes: int = 0
    links: int = 0
    conflicts: list[str] = field(default_factory=list)


def _when(v: Any) -> Any:
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def _fact_chains(conn, tenant_id: str, cref: str) -> dict[int, list]:
    out: dict[int, list] = {}
    for r in conn.execute(select(FR).where(FR.c.tenant_id == tenant_id, FR.c.cause_ref == cref).order_by(FR.c.id)):
        out.setdefault(r.fact_id, []).append(r)
    return out


def _registry_chains(conn, tenant_id: str, cref: str) -> dict[tuple, list]:
    """Registry revisions of the import, by what they are about: (entity, registry id), (programme, ref) or
    (link, registry id, subject)."""
    out: dict[tuple, list] = {}
    for r in conn.execute(select(RR).where(RR.c.tenant_id == tenant_id, RR.c.cause_ref == cref).order_by(RR.c.id)):
        key = ("entity", r.registry_id) if r.kind == "entity" else (
            ("programme", r.subject) if r.kind == "programme" else ("link", r.registry_id, r.subject))
        out.setdefault(key, []).append(r)
    return out


def _links_of(conn, tenant_id: str, from_id: str) -> list[str]:
    return [f"{x.rel}:{x.to_kind}:{x.to_id}" for x in conn.execute(select(LK).where(
        LK.c.tenant_id == tenant_id, LK.c.from_id == from_id).order_by(LK.c.id))]


def _latest_registry(conn, tenant_id: str, key: tuple, cancelled: list[str]) -> int | None:
    q = select(func.max(RR.c.id)).where(RR.c.tenant_id == tenant_id, RR.c.kind == key[0],
                                        RR.c.cause_ref.notin_(cancelled) | RR.c.cause_ref.is_(None))
    if key[0] == "entity":
        q = q.where(RR.c.registry_id == key[1])
    elif key[0] == "programme":
        q = q.where(RR.c.subject == key[1])
    else:
        q = q.where(RR.c.registry_id == key[1], RR.c.subject == key[2])
    return conn.execute(q).scalar()


def undo_import(engine: Engine, tenant_id: str, import_id: int, *, actor: str) -> UndoResult:
    log = ImportLog(engine, tenant_id)
    rec = log.get(import_id)
    if rec is None:
        raise KeyError(import_id)
    if rec.status == "undone":
        raise ValueError(f"import {import_id} is already undone")
    if rec.status == "running":
        raise ValueError(f"import {import_id} is still running")
    cref, uref = cause_ref(import_id), f"undo-{import_id}"
    # imports already undone have cancelled themselves out: their revisions and undo revisions do not count as changes
    cancelled = [ref for r in log.list(10_000) if r.status == "undone" and r.id != import_id
                 for ref in (cause_ref(r.id), f"undo-{r.id}")]
    result = UndoResult()
    with engine.begin() as conn:
        fact_chains = _fact_chains(conn, tenant_id, cref)
        reg_chains = _registry_chains(conn, tenant_id, cref)
        for fid, chain in fact_chains.items():
            last = conn.execute(select(func.max(FR.c.id)).where(
                FR.c.fact_id == fid, FR.c.cause_ref.notin_(cancelled) | FR.c.cause_ref.is_(None))).scalar()
            if last != chain[-1].id:
                result.conflicts.append(f"fact {fid}")
        for key, chain in reg_chains.items():
            if _latest_registry(conn, tenant_id, key, cancelled) != max(r.id for r in chain):
                what = conn.execute(select(R.c.entity_id).where(R.c.id == key[1])).scalar() if key[0] != "programme" \
                    else key[1]
                result.conflicts.append(f"{key[0]} {what}" + (f" {key[2]}" if key[0] == "link" else ""))
        if result.conflicts:
            raise UndoRefused(result.conflicts)
        for fid, chain in fact_chains.items():
            before = conn.execute(select(F).where(F.c.id == fid).with_for_update()).one()
            first = chain[0].before
            if first is None:
                values = {"status": "stale", "value": None, "conflict_note": f"withdrawn: import {import_id} undone"}
            else:
                values = {k: (_when(first[k]) if k == "checked_at" else first[k]) for k in _FACT_FIELDS}
            conn.execute(update(F).where(F.c.id == fid).values(**values, updated_at=func.now()))
            after = conn.execute(select(F).where(F.c.id == fid)).one()
            conn.execute(FR.insert().values(tenant_id=tenant_id, fact_id=fid, action="undo",
                                            before=fact_snapshot(before), after=fact_snapshot(after), cause="import",
                                            cause_ref=uref, actor=actor))
            result.facts += 1
        # programmes first (they name registry rows), then links, then the entities themselves
        done_programmes: set[str] = set()
        for key, chain in reg_chains.items():
            if key[0] != "programme" or key[1] in done_programmes:
                continue
            done_programmes.add(key[1])
            first = chain[0].before
            owners = {r.registry_id for r in chain}
            cur = conn.execute(select(*[PG.c[c] for c in _PROGRAMME_FIELDS]).where(
                PG.c.tenant_id == tenant_id, PG.c.ref == key[1]).with_for_update()).one()
            conn.execute(update(PG).where(PG.c.tenant_id == tenant_id, PG.c.ref == key[1]).values(
                **{c: first[c] for c in _PROGRAMME_FIELDS}, updated_at=func.now()))
            for rid in owners:
                conn.execute(RR.insert().values(
                    tenant_id=tenant_id, registry_id=rid, kind="programme", subject=key[1], action="undo",
                    before=dict(cur._mapping), after={c: first[c] for c in _PROGRAMME_FIELDS}, cause="import",
                    cause_ref=uref, actor=actor))
            result.programmes += 1
        for key, chain in reg_chains.items():
            if key[0] != "link":
                continue
            rel, to_kind, to_id = chain[0].subject.split(":", 2)
            from_id = conn.execute(select(R.c.entity_id).where(R.c.id == key[1])).scalar_one()

            before_set = _links_of(conn, tenant_id, from_id)
            conn.execute(delete(LK).where(LK.c.tenant_id == tenant_id, LK.c.from_id == from_id, LK.c.rel == rel,
                                          LK.c.to_kind == to_kind, LK.c.to_id == to_id))
            conn.execute(RR.insert().values(
                tenant_id=tenant_id, registry_id=key[1], kind="link", subject=chain[0].subject, action="undo",
                before={"links": before_set}, after={"links": _links_of(conn, tenant_id, from_id)},
                cause="import", cause_ref=uref, actor=actor))
            result.links += 1
        for key, chain in reg_chains.items():
            if key[0] != "entity":
                continue
            rid = key[1]
            before = conn.execute(select(R).where(R.c.id == rid).with_for_update()).one()
            first = chain[0].before
            if first is None:
                values = {"status": "closed", "attrs": {**before.attrs, "withdrawn_by_import": import_id}}
            else:
                values = {k: (_when(first[k]) if k == "checked_at" else first[k]) for k in _REGISTRY_FIELDS}
            conn.execute(update(R).where(R.c.id == rid).values(**values, updated_at=func.now()))
            after = conn.execute(select(R).where(R.c.id == rid)).one()
            conn.execute(RR.insert().values(tenant_id=tenant_id, registry_id=rid, kind="entity", action="undo",
                                            before=registry_snapshot(before), after=registry_snapshot(after),
                                            cause="import", cause_ref=uref, actor=actor))
            result.registry += 1
        for ref in rec.programmes_created:  # a programme the import created leaves the registry
            conn.execute(update(PG).where(PG.c.tenant_id == tenant_id, PG.c.ref == ref).values(
                status="excluded", institution_id=None, campus_id=None, level=None, field=None, family=None,
                region=None, updated_at=func.now()))
        log.mark_undone(import_id, actor, conn)  # the same transaction: the log never disagrees with the data
    return result
