"""Migration 121: the Mirror confirm gate is gone (FOUR_FEATURES_SPEC 2.3, 2.4)."""

import importlib.util
import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from app.database import Base
import app.models  # noqa: F401 - registers every table on Base.metadata
from scripts.counselor_eval_support import StudentSession

BACKEND = Path(__file__).resolve().parents[1]
TABLE = "pai_counselor_mirror_feedback"


def _load():
    spec = importlib.util.spec_from_file_location("migration121", BACKEND / "alembic/versions/121_mirror_gate_removed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(fn):
    migration = _load()
    with patch.object(migration, "op", Mock()) as op:
        getattr(migration, fn)()
    return migration, op


def test_121_chains_after_120_and_the_model_is_gone():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("121", "120")
    assert TABLE not in Base.metadata.tables


def test_121_upgrade_cleans_up_then_drops_the_feedback_table():
    migration, op = _run("upgrade")
    assert [call.args[0] for call in op.execute.call_args_list] == list(migration.CLEANUP)
    count = len(migration.CLEANUP)
    assert {call[0] for call in op.method_calls[:count]} == {"execute"}
    assert op.method_calls[count][0] == "drop_table" and op.drop_table.call_args.args == (TABLE,)
    # Each stage event is written right before its move, and old drafts are cleared last.
    for event, update in (migration.MOVE_CONFIRMED_MIRROR, migration.MOVE_WAITING):
        assert event.startswith("INSERT INTO pai_student_journey_events") and update.startswith("UPDATE")
        assert migration.CLEANUP.index(event) + 1 == migration.CLEANUP.index(update)
    assert migration.CLEANUP.index(migration.CLEAR_OLD_DRAFTS) > migration.CLEANUP.index(migration.MOVE_WAITING[1])


def _database():
    connection = sqlite3.connect(":memory:")
    connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    connection.executescript("""
        CREATE TABLE background_jobs (id TEXT, job_type TEXT, status TEXT);
        CREATE TABLE pai_student_journeys (id TEXT, workspace_id TEXT, journey_type TEXT, current_stage TEXT,
                                           counselor_summary_draft TEXT, updated_at TEXT);
        CREATE TABLE pai_student_journey_events (id TEXT, journey_id TEXT, workspace_id TEXT, event_type TEXT,
                                                 payload TEXT, actor TEXT, created_at TEXT);
        CREATE TABLE pai_possibilities (id TEXT, workspace_id TEXT, status TEXT);
    """)
    return connection


def _clean(connection):
    # NOW() and jsonb_build_object are Postgres; SQLite spells them CURRENT_TIMESTAMP and json_object.
    for sql in _load().CLEANUP:
        connection.execute(sql.replace("NOW()", "CURRENT_TIMESTAMP").replace("jsonb_build_object", "json_object"))


CONFIRMED = '{"type": "mirror", "status": "confirmed", "version": 2}'
WAITING_DRAFT = '{"type": "mirror", "status": "awaiting_confirmation", "version": 1}'
STATE = '{"type": "mirror_state", "version": 1, "text": "You study."}'
COUNSELOR = "counselor_decision"


def test_migration_121_moves_waiting_journeys():
    connection = _database()
    connection.executemany("INSERT INTO pai_student_journeys VALUES (?, ?, ?, ?, ?, NULL)", [
        ("researching_paths", "w1", COUNSELOR, "RESEARCHING", CONFIRMED),
        ("assessing_no_paths", "w2", COUNSELOR, "ASSESSING", CONFIRMED),
        ("needs_info_paths", "w3", COUNSELOR, "NEEDS_INFO", None),
        ("mirror_confirmed_paths", "w4", COUNSELOR, "MIRROR", CONFIRMED),
        ("mirror_confirmed_no_paths", "w5", COUNSELOR, "MIRROR", CONFIRMED),
        ("mirror_waiting_paths", "w6", COUNSELOR, "MIRROR", WAITING_DRAFT),
        ("direction", "w7", COUNSELOR, "DIRECTION", STATE),
        ("other_type", "w8", "application", "RESEARCHING", CONFIRMED),
        ("dismissed_only", "w9", COUNSELOR, "RESEARCHING", CONFIRMED)])
    connection.executemany("INSERT INTO pai_possibilities VALUES (?, ?, ?)", [
        ("p1", "w1", "exploring"), ("p3", "w3", "suggested"), ("p4", "w4", "saved"), ("p6", "w6", "suggested"),
        ("p8", "w8", "suggested"), ("p9", "w9", "dismissed")])
    connection.executemany("INSERT INTO background_jobs VALUES (?, ?, ?)", [
        ("a", "counselor.mirror", "pending"), ("b", "counselor.mirror_research", "running"),
        ("c", "counselor.mirror", "succeeded"), ("d", "counselor.mirror_text", "pending")])
    _clean(connection)
    stages = dict(connection.execute("SELECT id, current_stage FROM pai_student_journeys"))
    assert stages == {
        "researching_paths": "PROPOSED", "assessing_no_paths": "MIRROR", "needs_info_paths": "PROPOSED",
        "mirror_confirmed_paths": "PROPOSED", "mirror_confirmed_no_paths": "MIRROR",
        "mirror_waiting_paths": "MIRROR", "direction": "DIRECTION", "other_type": "RESEARCHING",
        "dismissed_only": "MIRROR"}
    events = {journey: (json.loads(payload), actor, kind) for journey, payload, actor, kind in connection.execute(
        "SELECT journey_id, payload, actor, event_type FROM pai_student_journey_events")}
    assert set(events) == {"researching_paths", "assessing_no_paths", "needs_info_paths",
                           "mirror_confirmed_paths", "dismissed_only"}
    assert events["researching_paths"] == ({"from": "RESEARCHING", "to": "PROPOSED"}, "system:migration_121",
                                           "journey.stage_changed")
    assert events["assessing_no_paths"][0] == {"from": "ASSESSING", "to": "MIRROR"}
    assert events["mirror_confirmed_paths"][0] == {"from": "MIRROR", "to": "PROPOSED"}
    drafts = dict(connection.execute("SELECT id, counselor_summary_draft FROM pai_student_journeys"))
    # Old-shape Mirror drafts are cleared everywhere; the new state draft stays.
    assert {key for key, value in drafts.items() if value is not None} == {"direction"}
    assert drafts["direction"] == STATE
    assert {row[0] for row in connection.execute("SELECT id FROM background_jobs")} == {"c", "d"}


def test_121_downgrade_recreates_the_feedback_table_and_leaves_stages():
    migration, op = _run("downgrade")
    op.execute.assert_not_called()
    with StudentSession() as student:
        with student.engine.begin() as connection:
            assert TABLE not in inspect(connection).get_table_names()
            with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                migration.downgrade()
            columns = {column["name"] for column in inspect(connection).get_columns(TABLE)}
            assert columns == {"id", "workspace_id", "mirror_version", "understood", "certainty_after",
                               "certainty_before", "created_at"}
            with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                migration.op.drop_table(TABLE)
            assert TABLE not in inspect(connection).get_table_names()
