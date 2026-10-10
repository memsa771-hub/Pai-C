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


def test_retire_legacy_definitions_all_versions_and_restore_on_downgrade():
    path = Path(__file__).parents[1] / "alembic/versions/103_retire_legacy_vault_fields.py"
    spec = importlib.util.spec_from_file_location("retire_definitions", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "103" and migration.down_revision == "102"
    retired = ("education.cgpa", "education.backlogs", "tests.ielts.score")
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE pai_vault_field_definitions (id INTEGER PRIMARY KEY, key TEXT, version INTEGER, enabled BOOLEAN)"))
        db.execute(text("CREATE TABLE pai_vault_facts (field_key TEXT, value TEXT)"))
        for key in (*retired, "synthetic.current"):
            for version in (1, 2):
                db.execute(text("INSERT INTO pai_vault_field_definitions (key, version, enabled) VALUES (:key, :version, true)"),
                           {"key": key, "version": version})
            db.execute(text("INSERT INTO pai_vault_facts VALUES (:key, 'historical value')"), {"key": key})
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        rows = db.execute(text("SELECT key, version, enabled FROM pai_vault_field_definitions")).all()
        assert len(rows) == 8
        assert all(bool(enabled) == (key not in retired) for key, _, enabled in rows)
        assert db.execute(text("SELECT COUNT(*) FROM pai_vault_facts")).scalar_one() == 4
        with Operations.context(MigrationContext.configure(db)):
            migration.downgrade()
        assert db.execute(text("SELECT COUNT(*) FROM pai_vault_field_definitions WHERE enabled")).scalar_one() == 8


def test_memory_foundation_python_has_no_retired_specific_tokens():
    import re
    app = Path(__file__).parents[1] / "app"
    tokens = re.compile(r"(?<![a-z])(ielts|toefl|cgpa|pkr|inr)(?![a-z])|[\u20b9\u20a8]", re.IGNORECASE)
    violations = []
    for package in ("memory", "pai_c", "journey"):
        for path in (app / package).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if tokens.search(line):
                    violations.append(f"{path.relative_to(app)}:{number}")
    assert not violations, violations
