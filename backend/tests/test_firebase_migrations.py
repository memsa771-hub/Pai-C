"""Migrations 113–114: add the Firebase identity and devices, drop the old provider column."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

VERSIONS = Path(__file__).resolve().parents[1] / "alembic/versions"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_113_adds_firebase_uid_and_devices_and_drops_no_table():
    migration = _load("113_firebase_auth")
    assert (migration.revision, migration.down_revision) == ("113", "112")
    with patch.object(migration, "op", Mock()) as op:
        migration.upgrade()
        assert op.add_column.call_args.args[1].name == "firebase_uid"
        assert op.create_table.call_args.args[0] == "auth_devices"
        op.drop_table.assert_not_called()


def test_114_drops_only_the_old_provider_column():
    migration = _load("114_remove_supabase_uid")
    assert (migration.revision, migration.down_revision) == ("114", "113")
    with patch.object(migration, "op", Mock()) as op:
        migration.upgrade()
        op.drop_column.assert_called_once_with("users", "supabase_uid")
        op.drop_table.assert_not_called()
        migration.downgrade()
        assert op.add_column.call_args.args[1].name == "supabase_uid"
