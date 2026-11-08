"""P2-T4: migration os_0027 (`os_pages.read_method/language`, `os_not_readable`, script tags on snapshots)."""

import subprocess

import pytest
from sqlalchemy import create_engine, insert, inspect
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from tests.os.conftest import run_alembic

pytestmark = pytest.mark.req("R-72", "R-29")


def snap(**kw):
    return {"tenant_id": "pai", "url": "https://x.test/a", "sha256": kw.pop("sha", "h"), "text": "t", **kw}


def test_constraints(engine, clean):
    with engine.begin() as conn:
        conn.execute(insert(models.page_snapshots).values(snap(sha="1", language="ur")))
        conn.execute(insert(models.page_snapshots).values(snap(sha="2", language="arab")))  # a script tag
    for bad in ("arabic", "A", "u1"):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(insert(models.page_snapshots).values(snap(sha="3", language=bad)))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.pages).values(tenant_id="pai", url="u", read_method="guess"))
    row = {"tenant_id": "pai", "url": "u", "reason": "http_403"}
    with engine.begin() as conn:
        conn.execute(insert(models.not_readable).values(row))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.not_readable).values(row))  # one row per url, programme, field and year
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.not_readable).values({**row, "field": "f", "state": "gone"}))


def test_downgrade_refuses_with_rows_then_restores_the_old_shape(os_db, engine, clean):
    with engine.begin() as conn:
        conn.execute(insert(models.not_readable).values(tenant_id="pai", url="u", reason="x"))
    engine.dispose()
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(["downgrade", "os_0026"], os_db)
    eng = create_engine(os_db)
    with eng.begin() as conn:
        conn.execute(models.not_readable.delete())
        conn.execute(insert(models.page_snapshots).values(snap(language="arab")))
    eng.dispose()
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(["downgrade", "os_0026"], os_db)  # a snapshot carries a script tag: no silent loss
    eng = create_engine(os_db)
    with eng.begin() as conn:
        conn.execute(models.page_snapshots.delete())
    eng.dispose()
    run_alembic(["downgrade", "os_0026"], os_db)
    try:
        eng = create_engine(os_db)
        try:
            assert "os_not_readable" not in inspect(eng).get_table_names(schema=OS_SCHEMA)
            assert "read_method" not in {c["name"] for c in inspect(eng).get_columns("os_pages", schema=OS_SCHEMA)}
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)
