"""Migration 126: the per-student Vault version table (P1-T4, R-13)."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.database import Base
import app.models  # noqa: F401 - registers every table on Base.metadata

pytestmark = pytest.mark.req("R-13")

BACKEND = Path(__file__).resolve().parents[1]
TABLE = "pai_vault_versions"
COLUMNS = {"workspace_id", "version", "key_versions", "updated_at"}


def _load():
    spec = importlib.util.spec_from_file_location("migration126", BACKEND / "alembic/versions/126_vault_versions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrate(connection, fn):
    migration = _load()
    with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
        getattr(migration, fn)()


def test_126_chains_after_125_and_matches_the_model():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("126", "125")
    table = Base.metadata.tables[TABLE]
    assert set(table.columns.keys()) == COLUMNS
    assert [c.name for c in table.primary_key.columns] == ["workspace_id"]
    assert {fk.ondelete for fk in table.c.workspace_id.foreign_keys} == {"CASCADE"}


def test_126_upgrade_and_downgrade():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE workspaces (id TEXT PRIMARY KEY)"))
        _migrate(connection, "upgrade")
        assert COLUMNS == {c["name"] for c in inspect(connection).get_columns(TABLE)}
        connection.execute(text("INSERT INTO workspaces VALUES ('w')"))
        connection.execute(text(f"INSERT INTO {TABLE} (workspace_id) VALUES ('w')"))
        assert connection.execute(text(f"SELECT version FROM {TABLE}")).scalar() == 0
    with engine.begin() as connection:
        _migrate(connection, "downgrade")
        assert TABLE not in inspect(connection).get_table_names()
