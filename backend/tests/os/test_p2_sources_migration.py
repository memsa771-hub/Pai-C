"""P2-T3: migration os_0026 (`os_source_domains`, `os_page_snapshots`, `os_source_files`). Fictional data."""

import subprocess

import pytest
from sqlalchemy import create_engine, insert, inspect
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from tests.os.conftest import run_alembic

pytestmark = pytest.mark.req("R-24")


def test_tables_and_constraints(engine, clean):
    insp = inspect(engine)
    assert {"os_source_domains", "os_page_snapshots", "os_source_files"} <= set(insp.get_table_names(schema=OS_SCHEMA))
    base = {"tenant_id": "pai", "domain": "alpha.test", "region": "north", "family": "university"}
    with engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(**base, tier="institution"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(**base))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(**{**base, "region": "x"}, tier="bogus"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(**{**base, "region": "y"}, state="maybe"))


def test_downgrade_refused_with_rows_then_clean(os_db, engine, clean):
    with engine.begin() as conn:
        conn.execute(insert(models.source_domains).values(tenant_id="pai", domain="a.test"))
    engine.dispose()
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(["downgrade", "os_0025"], os_db)
    eng = create_engine(os_db)
    with eng.begin() as conn:
        conn.execute(models.source_domains.delete())
    eng.dispose()
    run_alembic(["downgrade", "os_0025"], os_db)
    try:
        eng = create_engine(os_db)
        try:
            assert "os_source_domains" not in inspect(eng).get_table_names(schema=OS_SCHEMA)
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)
