"""Undo an import by replaying the revisions it wrote, backwards (P2 spec §4.6; master R-68; P2-D9). Nothing is deleted:

- a fact the import inserted is withdrawn: status `stale`, value emptied, with a note naming the undone import;
- a fact or registry row the import changed goes back to what its first revision of the import recorded as `before`;
- a registry row the import inserted is `closed` (never deleted, R-60);
- a programme the import created is `excluded` and leaves the registry.

Every step is a new `undo` revision. If anything was changed by someone else after the import, the undo refuses and
changes nothing: it lists what moved."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select, update

from app.os import models
from app.os.knowledge.sheets.importlog import ImportLog, cause_ref
from app.os.knowledge.store import _snapshot as fact_snapshot
from app.os.registry.store import _snapshot as registry_snapshot

F, FR = models.knowledge_facts, models.fact_revisions
R, RR = models.registry, models.registry_revisions
PG = models.programmes
_FACT_FIELDS = ("value", "quote", "url", "checked_at", "status", "conflict_note", "source", "fact_class",
                "read_method", "language")
_REGISTRY_FIELDS = ("kind", "parent_id", "region", "institution_type", "name", "aliases", "official_domains", "status",
                    "successor_id", "list_ids", "source_url", "quote", "checked_at", "attrs")


class UndoRefused(RuntimeError):
    def __init__(self, conflicts: list[str]) -> None:
        super().__init__("undo refused: changed after the import: " + ", ".join(conflicts))
        self.conflicts = conflicts


@dataclass
class UndoResult:
    facts: int = 0
    registry: int = 0
    programmes: int = 0
    conflicts: list[str] = field(default_factory=list)


def _when(v: Any) -> Any:
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def _chains(conn, tenant_id: str, rev, key_col, cref: str) -> dict[int, list]:
    out: dict[int, list] = {}
    for r in conn.execute(select(rev).where(rev.c.tenant_id == tenant_id, rev.c.cause_ref == cref).order_by(rev.c.id)):
        out.setdefault(getattr(r, key_col), []).append(r)
    return out


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
    result = UndoResult()
    with engine.begin() as conn:
        fact_chains = _chains(conn, tenant_id, FR, "fact_id", cref)
        reg_chains = _chains(conn, tenant_id, RR, "registry_id", cref)
        for fid, chain in fact_chains.items():
            last = conn.execute(select(func.max(FR.c.id)).where(FR.c.fact_id == fid)).scalar()
            if last != chain[-1].id:
                result.conflicts.append(f"fact {fid}")
        for rid, chain in reg_chains.items():
            last = conn.execute(select(func.max(RR.c.id)).where(RR.c.registry_id == rid)).scalar()
            if last != chain[-1].id:
                ent = conn.execute(select(R.c.entity_id).where(R.c.id == rid)).scalar()
                result.conflicts.append(f"registry {ent}")
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
        for rid, chain in reg_chains.items():
            before = conn.execute(select(R).where(R.c.id == rid).with_for_update()).one()
            first = chain[0].before
            if first is None:
                values = {"status": "closed", "attrs": {**before.attrs, "withdrawn_by_import": import_id}}
            else:
                values = {k: (_when(first[k]) if k == "checked_at" else first[k]) for k in _REGISTRY_FIELDS}
            conn.execute(update(R).where(R.c.id == rid).values(**values, updated_at=func.now()))
            after = conn.execute(select(R).where(R.c.id == rid)).one()
            conn.execute(RR.insert().values(tenant_id=tenant_id, registry_id=rid, action="undo",
                                            before=registry_snapshot(before), after=registry_snapshot(after),
                                            cause="import", cause_ref=uref, actor=actor))
            result.registry += 1
        for ref in rec.programmes_created:
            conn.execute(update(PG).where(PG.c.tenant_id == tenant_id, PG.c.ref == ref).values(
                status="excluded", institution_id=None, campus_id=None, level=None, field=None, family=None,
                region=None, updated_at=func.now()))
            result.programmes += 1
    log.mark_undone(import_id, actor)
    return result
