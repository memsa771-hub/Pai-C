"""Migration 119: drop the old roadmap tables, clear dead jobs, unstick journeys."""

import importlib.util
import re
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from app.database import Base
import app.models  # noqa: F401 — registers every table on Base.metadata

BACKEND = Path(__file__).resolve().parents[1]
DROPPED = {"pai_roadmaps", "pai_roadmap_student_state", "pai_decision_records"}


def _load():
    spec = importlib.util.spec_from_file_location("migration119", BACKEND / "alembic/versions/119_drop_old_roadmaps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(fn):
    migration = _load()
    with patch.object(migration, "op", Mock()) as op:
        getattr(migration, fn)()
    return migration, op


def test_119_chains_after_118_and_models_are_gone():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("119", "118")
    assert not DROPPED & set(Base.metadata.tables)
    assert "roadmap_id" not in Base.metadata.tables["pai_possibilities"].columns


def test_119_upgrade_drops_children_first_then_the_column_then_roadmaps():
    _, op = _run("upgrade")
    steps = [(call[0], call.args[0]) for call in op.method_calls if call[0] in ("drop_table", "drop_column")]
    assert steps == [("drop_table", "pai_decision_records"), ("drop_table", "pai_roadmap_student_state"),
                     ("drop_column", "pai_possibilities"), ("drop_table", "pai_roadmaps")]
    assert op.drop_column.call_args.args == ("pai_possibilities", "roadmap_id")
    assert op.drop_constraint.call_args.args[:2] == ("pai_possibilities_roadmap_id_fkey", "pai_possibilities")
    order = [call[0] for call in op.method_calls]
    assert order.index("drop_constraint") < order.index("drop_column")
    dropped_indexes = {call.args[0] for call in op.drop_index.call_args_list}
    assert dropped_indexes == {"idx_decision_workspace_current", "idx_roadmap_student_state_journey",
                               "uq_roadmap_chosen_per_journey", "uq_roadmaps_journey_lane",
                               "idx_roadmaps_requirement_set", "idx_roadmaps_run", "idx_roadmaps_workspace_journey"}


def test_119_downgrade_recreates_the_tables_with_final_shapes():
    _, op = _run("downgrade")
    tables = {call.args[0]: call.args[1:] for call in op.create_table.call_args_list}
    assert set(tables) == DROPPED
    roadmap_columns = {c.name for c in tables["pai_roadmaps"] if hasattr(c, "name") and c.name}
    assert roadmap_columns >= {"lane", "scholarships", "requirement_set_id", "execution_run_id", "journey_id"}
    assert [call.args[0] for call in op.create_table.call_args_list][0] == "pai_roadmaps"
    assert op.add_column.call_args.args[0] == "pai_possibilities"
    assert op.add_column.call_args.args[1].name == "roadmap_id"
    assert {call.args[0] for call in op.create_index.call_args_list} == {
        "idx_roadmaps_workspace_journey", "idx_roadmaps_run", "idx_roadmaps_requirement_set",
        "uq_roadmaps_journey_lane", "uq_roadmap_chosen_per_journey", "idx_roadmap_student_state_journey",
        "idx_decision_workspace_current"}
    op.execute.assert_not_called()  # deleted jobs and old stages are not restored


def _database():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE background_jobs (id TEXT, job_type TEXT, status TEXT);
        CREATE TABLE pai_student_journeys (id TEXT, workspace_id TEXT, current_stage TEXT,
                                           counselor_summary_draft TEXT, updated_at TEXT);
        CREATE TABLE pai_route_decisions (workspace_id TEXT, withdrawn_at TEXT);
    """)
    return connection


def _statements(migration):
    # NOW() is Postgres; SQLite spells it CURRENT_TIMESTAMP. The rest runs as written.
    return [sql.replace("NOW()", "CURRENT_TIMESTAMP")
            for sql in (migration.DELETE_DEAD_JOBS, migration.MOVE_TO_CHOSEN, migration.MOVE_TO_PROPOSED)]


def test_119_upgrade_issues_the_cleanup_sql_before_any_drop():
    migration, op = _run("upgrade")
    assert [call.args[0] for call in op.execute.call_args_list] == [
        migration.DELETE_DEAD_JOBS, migration.MOVE_TO_CHOSEN, migration.MOVE_TO_PROPOSED]
    assert op.method_calls[2][0] == "execute" and op.method_calls[3][0] != "execute"


def test_119_deletes_only_live_jobs_of_the_dead_types():
    connection = _database()
    connection.executemany("INSERT INTO background_jobs VALUES (?, ?, ?)", [
        ("a", "roadmaps.mark_stale", "pending"), ("b", "research.refresh_stale", "pending"),
        ("c", "research.refresh_stale", "running"), ("d", "roadmaps.mark_stale", "succeeded"),
        ("e", "memory.extract", "pending"), ("f", "research.claim", "pending")])
    connection.execute(_statements(_load())[0])
    assert {row[0] for row in connection.execute("SELECT id FROM background_jobs")} == {"d", "e", "f"}


def test_119_moves_stuck_journeys_to_proposed_or_chosen():
    connection = _database()
    confirmed, draft = '{"type": "mirror", "status": "confirmed"}', '{"type": "mirror", "status": "draft"}'
    connection.executemany("INSERT INTO pai_student_journeys VALUES (?, ?, ?, ?, NULL)", [
        ("researching", "w1", "RESEARCHING", confirmed),
        ("assessing", "w2", "ASSESSING", confirmed),
        ("needs_info", "w3", "NEEDS_INFO", confirmed),
        ("withdrawn_only", "w4", "RESEARCHING", confirmed),
        ("unconfirmed", "w5", "RESEARCHING", draft),
        ("no_draft", "w6", "ASSESSING", None),
        ("other_stage", "w7", "DIRECTION", confirmed),
        ("proposed", "w8", "PROPOSED", confirmed)])
    connection.executemany("INSERT INTO pai_route_decisions VALUES (?, ?)", [
        ("w2", None), ("w3", None), ("w4", "2026-10-01"), ("w5", None), ("w7", None)])
    for sql in _statements(_load())[1:]:
        connection.execute(sql)
    stages = dict(connection.execute("SELECT id, current_stage FROM pai_student_journeys"))
    assert stages == {"researching": "PROPOSED", "assessing": "CHOSEN", "needs_info": "CHOSEN",
                      "withdrawn_only": "PROPOSED", "unconfirmed": "RESEARCHING", "no_draft": "ASSESSING",
                      "other_stage": "DIRECTION", "proposed": "PROPOSED"}


REMOVED = re.compile(r"\b(RoadmapStudentState|DecisionRecord|pai_roadmaps|pai_roadmap_student_state|"
                     r"pai_decision_records)\b|\bRoadmap(?=[(.,)])|\bPaiPossibility\.roadmap_id|\broadmap_id\b")


def test_no_app_or_script_file_references_the_removed_models():
    offenders = []
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if REMOVED.search(line):
                    offenders.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
