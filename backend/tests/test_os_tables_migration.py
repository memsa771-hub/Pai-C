"""Migration 115: drop the PAI OS tables this PAI C app no longer has code for."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.database import Base
import app.models  # noqa: F401 — registers every table on Base.metadata

VERSIONS = Path(__file__).resolve().parents[1] / "alembic/versions"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_115_drops_only_tables_without_a_model_or_a_surviving_reference():
    migration = _load("115_drop_os_tables")
    assert (migration.revision, migration.down_revision) == ("115", "114")
    dropped = set(migration.TABLES)
    assert not dropped & set(Base.metadata.tables)
    for table in Base.metadata.tables.values():
        for key in table.foreign_keys:
            assert key.column.table.name not in dropped, (table.name, key.target_fullname)


def test_115_drops_children_before_parents_and_cannot_be_undone():
    migration = _load("115_drop_os_tables")
    order = list(migration.TABLES)
    for child, parent in (("pai_application_requirements", "pai_application_plans"),
                          ("pai_application_routines", "pai_application_plans"),
                          ("pai_application_routines", "routines"),
                          ("browser_tabs", "browser_contexts")):
        assert order.index(child) < order.index(parent)
    with patch.object(migration, "op", Mock()) as op:
        migration.upgrade()
        assert [call.args[0] for call in op.execute.call_args_list] == [
            f'DROP TABLE IF EXISTS "{table}"' for table in order]
    with pytest.raises(RuntimeError, match="restore from a backup"):
        migration.downgrade()
