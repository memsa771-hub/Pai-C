"""Slice 6a Task 3: pack tables (os_0009), the profile value's source, and the pack stores (spec §3)."""

import pytest
from sqlalchemy import create_engine, inspect

from app.os.db import OS_SCHEMA
from app.os.documents.store import ProfileStore
from app.os.packs.store import PackFileStore, PackItemStore

PDF = b"%PDF-1.4\n% fictional\n"


def test_migration_up_down_up(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0008"], os_db)
    eng = create_engine(os_db)
    try:
        assert not set(inspect(eng).get_table_names(schema=OS_SCHEMA)) & {"os_pack_files", "os_pack_items"}
        assert "source" not in {c["name"] for c in inspect(eng).get_columns("os_profile_values", schema=OS_SCHEMA)}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_put_same_bytes_once(engine, clean):
    files = PackFileStore(engine, "pai")
    sha = files.put("stu-1", "p1", "passport", "passport.pdf", "application/pdf", PDF, pages=1)
    assert len(sha) == 64
    assert files.put("stu-1", "p2", "passport", "passport.pdf", "application/pdf", PDF, pages=1) == sha
    got = files.get("stu-1", sha)
    assert (got.data, got.filename, got.pages, got.size) == (PDF, "passport.pdf", 1, len(PDF))
    meta = files.meta("stu-1", sha)
    assert meta.filename == "passport.pdf" and not hasattr(meta, "data")


def test_file_is_per_student(engine, clean):
    files = PackFileStore(engine, "pai")
    sha = files.put("stu-1", "p1", "passport", "passport.pdf", "application/pdf", PDF, pages=1)
    assert files.get("stu-2", sha) is None and files.meta("stu-2", sha) is None
    assert files.put("stu-2", "p1", "passport", "p.pdf", "application/pdf", PDF, pages=1) == sha  # their own copy
    files.delete_for_student("stu-1")
    assert files.get("stu-1", sha) is None and files.get("stu-2", sha) is not None


def test_delete_for_item(engine, clean):
    files = PackFileStore(engine, "pai")
    a = files.put("stu-1", "p1", "passport", "a.pdf", "application/pdf", PDF, pages=1)
    b = files.put("stu-1", "p1", "degree", "b.pdf", "application/pdf", PDF + b"x", pages=1)
    files.delete_for_item("stu-1", "passport")
    assert files.get("stu-1", a) is None and files.get("stu-1", b) is not None


def test_profile_source_entered(engine, clean):
    profile = ProfileStore(engine, "pai")
    profile.set("stu-1", "packs.email", "sara@example.test", None, source="entered")
    profile.set("stu-1", "passport.surname", "KHAN", None)
    rows = {r["key"]: r for r in profile.all("stu-1")}
    assert rows["packs.email"]["source"] == "entered" and rows["passport.surname"]["source"] == "document"
    with pytest.raises(ValueError):
        profile.set("stu-1", "x", "y", None, source="guessed")


def test_items_tick_and_add(engine, clean):
    items = PackItemStore(engine, "pai")
    items.tick("stu-1", "p1", "fee_paid")
    items.tick("stu-1", "p1", "fee_paid")  # idempotent
    assert items.ticked("stu-1", "p1") == {"fee_paid"} and items.ticked("stu-1", "p2") == set()
    items.untick("stu-1", "p1", "fee_paid")
    assert items.ticked("stu-1", "p1") == set()
    k1, k2 = items.add("stu-1", "p1", "Module descriptions"), items.add("stu-1", "p1", "Two references")
    assert (k1, k2) == ("added:1", "added:2")
    assert items.added("stu-1", "p1") == [("added:1", "Module descriptions"), ("added:2", "Two references")]


def test_tenant_isolation(engine, clean):
    files, other = PackFileStore(engine, "pai"), PackFileStore(engine, "other")
    sha = files.put("stu-1", "p1", "passport", "a.pdf", "application/pdf", PDF, pages=1)
    assert other.get("stu-1", sha) is None
    PackItemStore(engine, "pai").tick("stu-1", "p1", "fee_paid")
    assert PackItemStore(engine, "other").ticked("stu-1", "p1") == set()
