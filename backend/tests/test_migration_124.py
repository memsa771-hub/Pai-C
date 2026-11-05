"""Migration 124: decision versions and the Counsellor-side OS outbox (R-79)."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.database import Base
import app.models  # noqa: F401 - registers every table on Base.metadata

pytestmark = pytest.mark.req("R-79")

BACKEND = Path(__file__).resolve().parents[1]
DECISIONS = "pai_route_decisions"
OUTBOX = "pai_os_outbox"
NEW_COLUMNS = {"decision_version", "status", "origin_country", "destination_country", "level", "path_ref",
               "places", "intake", "os_supported", "authorized_at", "guardian_authorized_at", "guardian_required"}
OUTBOX_COLUMNS = {"id", "workspace_id", "kind", "key", "payload", "status", "attempts", "last_error",
                  "created_at", "delivered_at"}


def _load():
    spec = importlib.util.spec_from_file_location("migration124",
                                                  BACKEND / "alembic/versions/124_decision_versions_outbox.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _database_at_123():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE workspaces (id TEXT PRIMARY KEY)"))
        connection.execute(text("""
            CREATE TABLE pai_route_decisions (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                field_key TEXT NOT NULL, possibility_id TEXT, title TEXT NOT NULL, verdict JSON NOT NULL,
                route JSON NOT NULL, steps JSON NOT NULL, steps_done JSON NOT NULL,
                chosen_at TIMESTAMP NOT NULL, withdrawn_at TIMESTAMP)"""))
        connection.execute(text("CREATE UNIQUE INDEX uq_route_decision_active ON pai_route_decisions "
                                "(workspace_id) WHERE withdrawn_at IS NULL"))
        connection.execute(text("CREATE INDEX idx_route_decisions_workspace ON pai_route_decisions "
                                "(workspace_id, chosen_at)"))
    return engine


def _migrate(connection, fn):
    migration = _load()
    with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
        getattr(migration, fn)()


def test_124_chains_after_123_and_matches_the_model():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("124", "123")
    decisions = Base.metadata.tables[DECISIONS]
    assert NEW_COLUMNS <= set(decisions.columns.keys())
    assert not decisions.c.decision_version.nullable and not decisions.c.places.nullable
    assert decisions.c.intake.nullable and decisions.c.path_ref.nullable
    assert {index.name: index.unique for index in decisions.indexes}["uq_route_decision_version"] is True
    assert "uq_route_decision_active" in {index.name for index in decisions.indexes}
    assert set(Base.metadata.tables[OUTBOX].columns.keys()) == OUTBOX_COLUMNS
    assert Base.metadata.tables[OUTBOX].c.key.unique


def _insert(connection, ident, workspace, chosen, withdrawn=None):
    connection.execute(text(
        "INSERT INTO pai_route_decisions VALUES (:id, :w, 'cs', NULL, :title, '{\"a\": 1}', '{\"b\": 2}', "
        "'[{\"key\": \"s\"}]', '[\"s\"]', :c, :x)"),
        {"id": ident, "w": workspace, "title": "T-" + ident, "c": chosen, "x": withdrawn})


def test_124_backfills_versions_and_withdrawn_rows():
    t1, t2, t3 = "2026-01-01 10:00:00", "2026-01-02 10:00:00", "2026-01-03 10:00:00"
    engine = _database_at_123()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO workspaces VALUES ('w1'), ('w2')"))
        _insert(connection, "a", "w1", t1, t2)
        _insert(connection, "b", "w1", t3)
        _insert(connection, "c", "w2", t1)
        _migrate(connection, "upgrade")
        rows = connection.execute(text(
            "SELECT id, workspace_id, decision_version, status, title, chosen_at, withdrawn_at, steps_done, "
            "places, os_supported, guardian_required FROM pai_route_decisions "
            "ORDER BY workspace_id, decision_version")).fetchall()
        assert [(r.workspace_id, r.decision_version, r.status) for r in rows] == [
            ("w1", 1, "chosen"), ("w1", 2, "withdrawn"), ("w1", 3, "chosen"), ("w2", 1, "chosen")]
        original, withdrawn, active, other = rows
        assert original.id == "a" and original.withdrawn_at.startswith(t2[:10])
        assert withdrawn.id not in {"a", "b", "c"} and withdrawn.title == "T-a"
        assert withdrawn.chosen_at == withdrawn.withdrawn_at and withdrawn.chosen_at.startswith(t2[:10])
        assert withdrawn.steps_done == "[]"  # a withdrawal has no steps done, like the live withdraw()
        assert active.id == "b" and active.withdrawn_at is None
        assert other.withdrawn_at is None
        assert all(r.places == "[]" and not r.os_supported and not r.guardian_required for r in rows)
        names = set(inspect(connection).get_table_names())
        assert OUTBOX in names
        assert NEW_COLUMNS <= {c["name"] for c in inspect(connection).get_columns(DECISIONS)}
        indexes = {i["name"]: i for i in inspect(connection).get_indexes(DECISIONS)}
        assert indexes["uq_route_decision_version"]["unique"] and "uq_route_decision_active" in indexes
        # one active row per workspace still holds
        with pytest.raises(Exception):
            connection.execute(text(
                "INSERT INTO pai_route_decisions (id, workspace_id, field_key, title, verdict, route, steps, "
                "steps_done, chosen_at, decision_version, places) VALUES ('z', 'w1', 'f', 't', '{}', '{}', '[]', "
                "'[]', :c, 9, '[]')"), {"c": t3})


def test_124_downgrade_drops_what_it_added():
    engine = _database_at_123()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO workspaces VALUES ('w1')"))
        _insert(connection, "a", "w1", "2026-01-01 10:00:00", "2026-01-02 10:00:00")
        _insert(connection, "b", "w1", "2026-01-03 10:00:00")
        _migrate(connection, "upgrade")
        _migrate(connection, "downgrade")
        inspector = inspect(connection)
        assert OUTBOX not in inspector.get_table_names()
        assert not NEW_COLUMNS & {c["name"] for c in inspector.get_columns(DECISIONS)}
        names = {i["name"] for i in inspector.get_indexes(DECISIONS)}
        assert "uq_route_decision_version" not in names and "uq_route_decision_active" in names
        assert {r.id for r in connection.execute(text("SELECT id FROM pai_route_decisions"))} == {"a", "b"}


def test_124_a_change_of_route_is_not_a_withdrawal():
    """Final review I2: the old choose() stamped the previous row's withdrawn_at with the new row's chosen_at. That is
    a change (v1 A, v2 B, as the live code writes it), not a withdrawal; a real withdrawal still gets its row."""
    t1, t2, t3, t4, t5 = ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "2026-01-03 10:00:00",
                          "2026-01-04 10:00:00", "2026-01-05 10:00:00")
    engine = _database_at_123()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO workspaces VALUES ('w1'), ('w2')"))
        _insert(connection, "a", "w1", t1, t2)  # changed to b at t2
        _insert(connection, "b", "w1", t2, t3)  # really withdrawn at t3
        _insert(connection, "c", "w1", t4, t5)  # withdrawn at t5; the next row (another workspace's) does not count
        _insert(connection, "d", "w2", t5, t5)  # withdrawn at once; nothing follows

        _migrate(connection, "upgrade")
        rows = connection.execute(text(
            "SELECT id, workspace_id, decision_version, status, title, chosen_at, steps_done FROM pai_route_decisions "
            "ORDER BY workspace_id, decision_version")).fetchall()
        assert [(r.workspace_id, r.decision_version, r.status, r.title) for r in rows] == [
            ("w1", 1, "chosen", "T-a"), ("w1", 2, "chosen", "T-b"), ("w1", 3, "withdrawn", "T-b"),
            ("w1", 4, "chosen", "T-c"), ("w1", 5, "withdrawn", "T-c"),
            ("w2", 1, "chosen", "T-d"), ("w2", 2, "withdrawn", "T-d")]
        assert [r.steps_done for r in rows if r.status == "withdrawn"] == ["[]", "[]", "[]"]
        assert rows[2].chosen_at.startswith(t3[:10])
