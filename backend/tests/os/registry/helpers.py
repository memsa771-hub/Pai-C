"""Fictional registry data for the P2-T2 tests: invented names on `.test` domains, never real bodies (P2 spec §5)."""

from datetime import UTC, datetime

from app.os.registry.model import RegistryEntry
from app.os.registry.store import RegistryStore

AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
LIST_URL = "https://lists.alpha.test/universities"


def olist(slug="alpha-list", *, rows=3, region="national", **attrs) -> RegistryEntry:
    return RegistryEntry(
        entity_id=f"list:{slug}", kind="official_list", name="Alpha recognised institutions", region=region,
        source_url=LIST_URL, checked_at=AT, institution_type="university",
        attrs={"body": "Alpha Regulator", "row_count": rows, "count_confirmed": True, **attrs})


def inst(slug, *, region="punjab", lists=("list:alpha-list",), **kw) -> RegistryEntry:
    return RegistryEntry(
        entity_id=f"inst:{slug}", kind="institution", name=f"{slug.title()} Test University", region=region,
        list_ids=tuple(lists), source_url=LIST_URL, quote=f"{slug.title()} Test University", checked_at=AT,
        institution_type="university", **kw)


def child(kind, prefix, slug, parent, **kw) -> RegistryEntry:
    return RegistryEntry(entity_id=f"{prefix}:{slug}", kind=kind, name=f"{slug.title()} ({kind})", parent_id=parent,
                         source_url="https://admissions.alpha.test/system", quote=f"{slug} on the page",
                         checked_at=AT, **kw)


def store(engine) -> RegistryStore:
    return RegistryStore(engine, "pai")


def seed_basic(s: RegistryStore, *, rows=2) -> None:
    """One list, `rows` published, two institutions loaded."""
    s.record(olist(rows=rows), cause="import")
    s.record(inst("one"), cause="import")
    s.record(inst("two", region="sindh"), cause="import")


def put(k, scope, ref, field, fact) -> int:
    """Writes a fact. `verified` only comes through review (T1), so it is written as confirmed, then reviewed."""
    from dataclasses import replace as _replace
    if fact.status != "verified":
        return k.upsert(scope, ref, field, fact)
    fid = k.upsert(scope, ref, field, _replace(fact, status="confirmed"))
    k.set_status(fid, "verified", cause="review")
    return fid
