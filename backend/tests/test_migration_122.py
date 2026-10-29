"""Migration 122: the journey stage sync columns and the dead Mirror index."""

import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from app.database import Base
import app.models  # noqa: F401 - registers every table on Base.metadata

BACKEND = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("migration122", BACKEND / "alembic/versions/122_journey_stage_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(fn):
    migration = _load()
    with patch.object(migration, "op", Mock()) as op:
        getattr(migration, fn)()
    return migration, op


def test_122_chains_after_121_and_matches_the_model():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("122", "121")
    columns = Base.metadata.tables["pai_student_journeys"].columns
    assert {"mirror_ready_at", "replan_at"} <= set(columns.keys())
    indexes = {index.name for index in Base.metadata.tables["background_jobs"].indexes}
    assert "uq_counselor_mirror_pending" not in indexes


def test_122_upgrade_and_downgrade():
    _, op = _run("upgrade")
    assert [call.args[1] for call in op.add_column.call_args_list] and \
        [call.args[1].name for call in op.add_column.call_args_list] == ["mirror_ready_at", "replan_at"]
    op.drop_index.assert_called_once_with("uq_counselor_mirror_pending", table_name="background_jobs")
    _, op = _run("downgrade")
    assert op.create_index.call_args.args[0] == "uq_counselor_mirror_pending"
    assert [call.args[1] for call in op.drop_column.call_args_list] == ["replan_at", "mirror_ready_at"]


def test_122_backfills_replan_for_journeys_already_back_in_direction():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE pai_student_journeys (id TEXT, journey_type TEXT, current_stage TEXT, replan_at TEXT);
        CREATE TABLE pai_student_journey_events (id TEXT, journey_id TEXT, event_type TEXT, payload TEXT,
                                                 created_at TEXT);
    """)
    connection.executemany("INSERT INTO pai_student_journeys VALUES (?, 'counselor_decision', ?, NULL)", [
        ("rethought", "DIRECTION"), ("escalated", "DIRECTION"), ("first_time", "DIRECTION"), ("proposed", "PROPOSED")])
    connection.executemany("INSERT INTO pai_student_journey_events VALUES (?, ?, 'journey.stage_changed', ?, ?)", [
        ("e1", "rethought", '{"from": "MIRROR", "to": "PROPOSED"}', "2026-01-01"),
        ("e2", "rethought", '{"from": "PROPOSED", "to": "DIRECTION"}', "2026-01-02"),
        ("e3", "escalated", '{"from": "CHOSEN", "to": "DIRECTION"}', "2026-01-02"),
        ("e4", "first_time", '{"from": "FOUNDATION", "to": "DIRECTION"}', "2026-01-02"),
        ("e5", "proposed", '{"from": "MIRROR", "to": "PROPOSED"}', "2026-01-02")])
    connection.execute(_load().BACKFILL_REPLAN.replace("NOW()", "CURRENT_TIMESTAMP"))
    replanning = {row[0] for row in connection.execute(
        "SELECT id FROM pai_student_journeys WHERE replan_at IS NOT NULL")}
    assert replanning == {"rethought", "escalated"}
