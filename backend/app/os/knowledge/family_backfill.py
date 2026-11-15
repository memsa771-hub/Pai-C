"""The programme family backfill (P3-T2, ADR-001 D4): sets `family` on programmes imported before the importer wrote
it, by the importer's own rule.

The rule: an import's programmes belong to the family its run was given (`--family`), unless the official lists of the
programme's institution name another family; then the programme is left alone and reported
(`family_conflicts_with_list`). The imports did not record their run's `--family`, so the operator names the family
together with the imports it applies to. Nothing is guessed: a programme no named import placed is never touched.

- A dry run by default: it reports what would change and writes nothing.
- `apply`: each change goes through `RegistryStore.link_programme`, so it is a `programme` revision of the institution
  with the six columns before and after, cause `import`, and the run's cause_ref `family-backfill-<UTC time>`.
- `undo_backfill(cause_ref)` puts each programme's family back to its `before`, as `undo-<cause_ref>` revisions. It
  refuses, and changes nothing, when a programme changed after the backfill, or the run is unknown or already undone.

No Alembic migration: the column exists since os_0027."""

import re
from dataclasses import dataclass, field

from sqlalchemy import Engine, func, select

from app.os import clock, models
from app.os.knowledge.sheets.importlog import ImportLog, cause_ref as import_cause_ref
from app.os.registry.store import RegistryStore, kept_lists

PG, R, RR = models.programmes, models.registry, models.registry_revisions
PREFIX = "family-backfill-"
_CODE = re.compile(r"^[a-z][a-z0-9_]*$")  # a registry / allow-list family code (the playbook's FAMILY_CODE)


class BackfillRefused(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    ref: str
    institution_id: str
    before: str | None
    after: str


@dataclass(frozen=True)
class Skipped:
    ref: str
    reason: str  # not_found | excluded | not_placed | family_already_set | family_conflicts_with_list
    detail: str = ""


@dataclass
class BackfillResult:
    family: str
    imports: tuple[int, ...]
    applied: bool
    cause_ref: str | None = None
    changes: list[Change] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    unchanged: int = 0  # already of this family


@dataclass
class UndoResult:
    cause_ref: str
    restored: list[str] = field(default_factory=list)


def _list_families(conn, tenant_id: str) -> dict[str, str]:
    """Official list id -> its family (`attrs.family`, H3 data), for the lists that name one."""
    rows = conn.execute(select(R.c.entity_id, R.c.attrs).where(R.c.tenant_id == tenant_id,
                                                               R.c.kind == "official_list")).all()
    return {r.entity_id: str(r.attrs["family"]) for r in rows if (r.attrs or {}).get("family")}


def _placed_by(conn, tenant_id: str, import_id: int) -> list[str]:
    """The programmes an import placed in the registry (its `programme` revisions)."""
    return sorted(set(conn.execute(select(RR.c.subject).where(
        RR.c.tenant_id == tenant_id, RR.c.kind == "programme",
        RR.c.cause_ref == import_cause_ref(import_id))).scalars()))


def plan_backfill(engine: Engine, tenant_id: str, *, family: str, imports: list[int] | tuple[int, ...]
                  ) -> BackfillResult:
    """What the backfill would change. Nothing is written."""
    if not _CODE.match(family or ""):
        raise BackfillRefused(f"'{family}' is not a family code (lowercase letters, digits and _)")
    if not imports:
        raise BackfillRefused("name the imports whose run had this family (--import ID, may repeat)")
    log = ImportLog(engine, tenant_id)
    for i in imports:
        rec = log.get(i)
        if rec is None:
            raise BackfillRefused(f"import {i} does not exist")
        if rec.status != "done":
            raise BackfillRefused(f"import {i} is {rec.status}, not done")
    res = BackfillResult(family=family, imports=tuple(dict.fromkeys(imports)), applied=False)
    with engine.connect() as conn:
        fams = _list_families(conn, tenant_id)
        refs = sorted({ref for i in res.imports for ref in _placed_by(conn, tenant_id, i)})
        for ref in refs:
            p = conn.execute(select(PG).where(PG.c.tenant_id == tenant_id, PG.c.ref == ref)).first()
            if p is None:
                res.skipped.append(Skipped(ref, "not_found"))
            elif p.status == "excluded":
                res.skipped.append(Skipped(ref, "excluded"))
            elif p.institution_id is None:
                res.skipped.append(Skipped(ref, "not_placed"))
            elif p.family == family:
                res.unchanged += 1
            elif p.family is not None:
                res.skipped.append(Skipped(ref, "family_already_set", p.family))
            else:
                inst = conn.execute(select(R).where(R.c.tenant_id == tenant_id,
                                                    R.c.entity_id == p.institution_id)).first()
                named = sorted({fams[x] for x in (kept_lists(inst) if inst is not None else ()) if x in fams})
                if named and family not in named:
                    res.skipped.append(Skipped(ref, "family_conflicts_with_list",
                                               f"{p.institution_id} is on lists of family {', '.join(named)}"))
                else:
                    res.changes.append(Change(ref, p.institution_id, p.family, family))
    return res


def run_backfill(engine: Engine, tenant_id: str, *, family: str, imports: list[int] | tuple[int, ...],
                 apply: bool = False, actor: str = "os.family_backfill") -> BackfillResult:
    """A dry run unless `apply`. With `apply`, every change is a revision carrying the run's cause_ref."""
    res = plan_backfill(engine, tenant_id, family=family, imports=imports)
    if not apply or not res.changes:
        return res
    res.applied, res.cause_ref = True, PREFIX + clock.now().strftime("%Y%m%dT%H%M%S%fZ")
    reg = RegistryStore(engine, tenant_id)
    for c in res.changes:
        reg.link_programme(c.ref, institution_id=c.institution_id, family=c.after, cause="import",
                           cause_ref=res.cause_ref, actor=actor)
    return res


def undone_runs(conn, tenant_id: str) -> list[str]:
    """The cause_refs of backfill runs that were undone, with their undo refs. Together they change nothing, so the
    import undo does not count them as a change after the import."""
    refs = set(conn.execute(select(RR.c.cause_ref).distinct().where(
        RR.c.tenant_id == tenant_id, RR.c.kind == "programme", RR.c.cause_ref.like(f"undo-{PREFIX}%"))).scalars())
    return [x for r in sorted(refs) for x in (r.removeprefix("undo-"), r)]


def undo_backfill(engine: Engine, tenant_id: str, cause_ref: str, *, actor: str = "os.family_backfill") -> UndoResult:
    if not cause_ref.startswith(PREFIX):
        raise BackfillRefused(f"'{cause_ref}' is not a family backfill run ({PREFIX}...)")
    with engine.connect() as conn:
        if conn.execute(select(RR.c.id).where(RR.c.tenant_id == tenant_id,
                                              RR.c.cause_ref == f"undo-{cause_ref}").limit(1)).first():
            raise BackfillRefused(f"{cause_ref} is already undone")
        revs = conn.execute(select(RR).where(RR.c.tenant_id == tenant_id, RR.c.kind == "programme",
                                             RR.c.cause_ref == cause_ref).order_by(RR.c.id)).all()
        if not revs:
            raise BackfillRefused(f"no backfill run {cause_ref}")
        first: dict = {}
        for r in revs:
            first.setdefault(r.subject, r)
        moved = []
        for ref in first:
            last = conn.execute(select(func.max(RR.c.id)).where(
                RR.c.tenant_id == tenant_id, RR.c.kind == "programme", RR.c.subject == ref)).scalar()
            if last != max(r.id for r in revs if r.subject == ref):
                moved.append(ref)
        if moved:
            raise BackfillRefused("undo refused: changed after the backfill: " + ", ".join(moved))
    out, reg = UndoResult(cause_ref), RegistryStore(engine, tenant_id)
    for ref, r in first.items():
        before = r.before or {}
        reg.link_programme(ref, institution_id=before.get("institution_id") or r.after["institution_id"],
                           family=before.get("family"), clear=True, cause="import", cause_ref=f"undo-{cause_ref}",
                           actor=actor)
        out.restored.append(ref)
    return out
