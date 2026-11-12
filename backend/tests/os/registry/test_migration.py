"""P2-T2: the registry tables, the programme-level columns and the `registry` fact scope (P2 spec §4.1; R-32, R-33)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import IntegrityError

from app.os import models

pytestmark = pytest.mark.req("R-32")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)


def reg(**kw) -> dict:
    return {"tenant_id": "pai", "entity_id": "inst:alpha", "kind": "institution", "name": "Alpha Test University",
            "source_url": "https://lists.alpha.test/universities", "checked_at": AT, **kw}


def test_tables_and_columns(engine, clean):
    names = inspect(engine).get_table_names(schema="os")
    for t in ("os_registry", "os_registry_revisions", "os_registry_links"):
        assert t in names
    cols = {c["name"] for c in inspect(engine).get_columns("os_programmes", schema="os")}
    assert {"institution_id", "campus_id", "level", "field", "family", "region"} <= cols


def test_registry_checks_and_unique(engine, clean):
    with engine.begin() as conn:
        conn.execute(insert(models.registry).values(**reg()))
    for bad in ({"kind": "college"}, {"status": "gone", "entity_id": "inst:b"}, {}):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(insert(models.registry).values(**reg(**bad)))
    with engine.begin() as conn:  # the same id for another tenant is a different row
        conn.execute(insert(models.registry).values(**reg(tenant_id="other")))


def test_registry_scope_for_facts(engine, clean):
    base = {"tenant_id": "pai", "ref": "inst:alpha", "field": "deadline_close", "intake_year": 2027, "checked_at": AT,
            "status": "unconfirmed"}
    with engine.begin() as conn:
        conn.execute(insert(models.knowledge_facts).values(**base, scope="registry"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.knowledge_facts).values(**{**base, "field": "x"}, scope="planet"))


def test_revisions_keep_their_entity(engine, clean):
    with engine.begin() as conn:
        rid = conn.execute(insert(models.registry).values(**reg()).returning(models.registry.c.id)).scalar_one()
        conn.execute(insert(models.registry_revisions).values(
            tenant_id="pai", registry_id=rid, action="insert", after={}, cause="import"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_registry WHERE id = :i"), {"i": rid})


def test_downgrade_refuses_with_data_then_round_trips(os_db, engine, clean):
    from tests.os.conftest import run_alembic

    with engine.begin() as conn:
        conn.execute(insert(models.registry).values(**reg()))
    with pytest.raises(Exception):
        run_alembic(["downgrade", "os_0026"], os_db)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_registry"))
    run_alembic(["downgrade", "os_0026"], os_db)
    try:
        assert "os_registry" not in inspect(engine).get_table_names(schema="os")
        assert "institution_id" not in {c["name"] for c in inspect(engine).get_columns("os_programmes", schema="os")}
    finally:
        run_alembic(["upgrade", "os@head"], os_db)
    assert "os_registry" in inspect(engine).get_table_names(schema="os")
