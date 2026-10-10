"""Offline checks for removal of obsolete discovery storage."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_slot_cleanup_drops_only_the_orphan_table():
    path = Path(__file__).parents[1] / "alembic/versions/102_drop_counselor_slot_answers.py"
    spec = importlib.util.spec_from_file_location("slot_cleanup", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "102" and migration.down_revision == "101"
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        for name in ("pai_counselor_slot_answers", "pai_profile_requirements", "pai_profile_field_responses"):
            db.execute(text(f"CREATE TABLE {name} (id TEXT PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert set(inspect(db).get_table_names()) == {"pai_profile_requirements", "pai_profile_field_responses"}
