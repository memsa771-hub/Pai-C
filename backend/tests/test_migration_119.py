"""Migration 119: drop the old roadmap tables and clean up what the old system left."""

import asyncio
import importlib.util
import json
import re
import sqlite3
import uuid
from types import SimpleNamespace
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
    op.drop_constraint.assert_not_called()  # drop_column takes the FK with it
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
    connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    connection.executescript("""
        CREATE TABLE background_jobs (id TEXT, job_type TEXT, status TEXT);
        CREATE TABLE pai_student_journeys (id TEXT, workspace_id TEXT, journey_type TEXT, current_stage TEXT,
                                           counselor_summary_draft TEXT, active_goal TEXT,
                                           current_objective TEXT, updated_at TEXT);
        CREATE TABLE pai_student_journey_events (id TEXT, journey_id TEXT, workspace_id TEXT, event_type TEXT,
                                                 payload TEXT, actor TEXT, created_at TEXT);
        CREATE TABLE pai_route_decisions (id TEXT, workspace_id TEXT, possibility_id TEXT, field_key TEXT,
                                          title TEXT, route TEXT, withdrawn_at TEXT);
        CREATE TABLE pai_possibilities (id TEXT, status TEXT, updated_at TEXT);
        CREATE TABLE execution_runs (id TEXT, task_type TEXT, status TEXT, pending_action TEXT, error TEXT,
                                     completed_at TEXT, updated_at TEXT);
    """)
    return connection


def _clean(connection):
    # NOW() and jsonb_build_object are Postgres; SQLite spells them CURRENT_TIMESTAMP and json_object.
    for sql in _load().CLEANUP:
        connection.execute(sql.replace("NOW()", "CURRENT_TIMESTAMP").replace("jsonb_build_object", "json_object"))


def test_119_upgrade_issues_the_cleanup_sql_before_any_drop():
    migration, op = _run("upgrade")
    assert [call.args[0] for call in op.execute.call_args_list] == list(migration.CLEANUP)
    count = len(migration.CLEANUP)
    assert {call[0] for call in op.method_calls[:count]} == {"execute"} and op.method_calls[count][0] != "execute"


def test_119_writes_each_stage_event_right_before_its_move():
    migration = _load()
    for event, update in (migration.UNCHOOSE, migration.MOVE_TO_CHOSEN, migration.MOVE_TO_PROPOSED):
        assert event.startswith("INSERT INTO pai_student_journey_events") and update.startswith("UPDATE")
        assert migration.CLEANUP.index(event) + 1 == migration.CLEANUP.index(update)


def test_119_deletes_only_live_jobs_of_the_dead_types():
    connection = _database()
    connection.executemany("INSERT INTO background_jobs VALUES (?, ?, ?)", [
        ("a", "roadmaps.mark_stale", "pending"), ("b", "research.refresh_stale", "pending"),
        ("c", "research.refresh_stale", "running"), ("d", "roadmaps.mark_stale", "succeeded"),
        ("e", "memory.extract", "pending"), ("f", "research.claim", "pending")])
    _clean(connection)
    assert {row[0] for row in connection.execute("SELECT id FROM background_jobs")} == {"d", "e", "f"}


CONFIRMED, DRAFT = '{"type": "mirror", "status": "confirmed"}', '{"type": "mirror", "status": "draft"}'
COUNSELOR, OLD_GOAL = "counselor_decision", '{"roadmap_id": "old"}'


def _journeys(connection, rows):
    connection.executemany("INSERT INTO pai_student_journeys VALUES (?, ?, ?, ?, ?, ?, ?, NULL)", rows)


def _decisions(connection, rows):
    connection.executemany("INSERT INTO pai_route_decisions VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (f"d-{ws}", ws, f"p-{ws}", "electrical_engineering", f"Route {ws}", '{"years": 4}', withdrawn)
        for ws, withdrawn in rows])


def _stages(connection):
    return dict(connection.execute("SELECT id, current_stage FROM pai_student_journeys"))


def _goals(connection):
    return {id_: (goal, objective) for id_, goal, objective in connection.execute(
        "SELECT id, active_goal, current_objective FROM pai_student_journeys")}


def _events(connection):
    return {journey: (json.loads(payload), actor, kind) for journey, payload, actor, kind in connection.execute(
        "SELECT journey_id, payload, actor, event_type FROM pai_student_journey_events")}


def test_119_moves_stuck_counselor_journeys_to_proposed_or_chosen():
    connection = _database()
    _journeys(connection, [
        ("researching", "w1", COUNSELOR, "RESEARCHING", CONFIRMED, None, None),
        ("assessing", "w2", COUNSELOR, "ASSESSING", CONFIRMED, None, None),
        ("needs_info", "w3", COUNSELOR, "NEEDS_INFO", CONFIRMED, None, None),
        ("withdrawn_only", "w4", COUNSELOR, "RESEARCHING", CONFIRMED, None, None),
        ("unconfirmed", "w5", COUNSELOR, "RESEARCHING", DRAFT, None, None),
        ("no_draft", "w6", COUNSELOR, "ASSESSING", None, None, None),
        ("other_stage", "w7", COUNSELOR, "DIRECTION", CONFIRMED, None, None),
        ("proposed", "w8", COUNSELOR, "PROPOSED", CONFIRMED, None, None),
        ("other_type", "w9", "application", "RESEARCHING", CONFIRMED, None, None)])
    _decisions(connection, [("w2", None), ("w3", None), ("w4", "2026-10-01"), ("w5", None), ("w7", None),
                            ("w9", None)])
    _clean(connection)
    assert _stages(connection) == {
        "researching": "PROPOSED", "assessing": "CHOSEN", "needs_info": "CHOSEN", "withdrawn_only": "PROPOSED",
        "unconfirmed": "RESEARCHING", "no_draft": "ASSESSING", "other_stage": "DIRECTION", "proposed": "PROPOSED",
        "other_type": "RESEARCHING"}
    goal, objective = _goals(connection)["assessing"]
    assert objective == "Route w2"
    assert json.loads(goal) == {"route_decision_id": "d-w2", "field_key": "electrical_engineering",
                                "title": "Route w2", "route": '{"years": 4}'}  # SQLite keeps route as text
    assert _goals(connection)["researching"] == (None, None)
    events = _events(connection)
    assert set(events) == {"researching", "assessing", "needs_info", "withdrawn_only"}
    assert events["assessing"] == ({"from": "ASSESSING", "to": "CHOSEN"}, "system:migration_119",
                                   "journey.stage_changed")
    assert events["researching"][0] == {"from": "RESEARCHING", "to": "PROPOSED"}


def test_119_unchooses_counselor_journeys_without_an_active_decision():
    connection = _database()
    current_goal = '{"route_decision_id": "d-w4"}'
    _journeys(connection, [
        ("old_choice", "w1", COUNSELOR, "CHOSEN", CONFIRMED, OLD_GOAL, "Old route"),
        ("old_unconfirmed", "w2", COUNSELOR, "CHOSEN", DRAFT, OLD_GOAL, "Old route"),
        ("withdrawn", "w3", COUNSELOR, "CHOSEN", CONFIRMED, OLD_GOAL, "Old route"),
        ("current", "w4", COUNSELOR, "CHOSEN", CONFIRMED, current_goal, "Route w4"),
        ("other_type", "w5", "application", "CHOSEN", CONFIRMED, OLD_GOAL, "Old route")])
    _decisions(connection, [("w3", "2026-10-01"), ("w4", None)])
    _clean(connection)
    assert _stages(connection) == {"old_choice": "PROPOSED", "old_unconfirmed": "DIRECTION",
                                   "withdrawn": "PROPOSED", "current": "CHOSEN", "other_type": "CHOSEN"}
    goals = _goals(connection)
    assert goals["old_choice"] == goals["old_unconfirmed"] == goals["withdrawn"] == (None, None)
    assert goals["current"] == (current_goal, "Route w4")
    assert goals["other_type"] == (OLD_GOAL, "Old route")
    events = _events(connection)
    assert set(events) == {"old_choice", "old_unconfirmed", "withdrawn"}
    assert events["old_choice"][0] == {"from": "CHOSEN", "to": "PROPOSED"}
    assert events["old_unconfirmed"][0] == {"from": "CHOSEN", "to": "DIRECTION"}


def test_119_returns_old_chosen_paths_to_saved():
    connection = _database()
    connection.executemany("INSERT INTO pai_possibilities VALUES (?, ?, NULL)", [
        ("p-w1", "chosen"), ("p-w2", "chosen"), ("orphan", "chosen"), ("kept", "saved"), ("explored", "exploring")])
    _decisions(connection, [("w1", None), ("w2", "2026-10-01")])
    # An active decision whose path was deleted must not hide every other row (NOT IN with NULL).
    connection.execute("INSERT INTO pai_route_decisions VALUES ('d-w3', 'w3', NULL, 'x', 'X', '{}', NULL)")
    _clean(connection)
    assert dict(connection.execute("SELECT id, status FROM pai_possibilities")) == {
        "p-w1": "chosen", "p-w2": "saved", "orphan": "saved", "kept": "saved", "explored": "exploring"}


def test_119_retires_unfinished_roadmap_research_runs():
    connection = _database()
    connection.executemany("INSERT INTO execution_runs VALUES (?, ?, ?, ?, NULL, NULL, NULL)", [
        ("pending", "roadmap_research", "pending", None), ("executing", "roadmap_research", "executing", None),
        ("waiting", "roadmap_research", "needs_user_action", '{"kind": "answer"}'),
        ("done", "roadmap_research", "completed", None), ("other", "path_explain", "pending", None)])
    _clean(connection)
    rows = {id_: rest for id_, *rest in connection.execute(
        "SELECT id, status, pending_action, error, completed_at FROM execution_runs")}
    for retired in ("pending", "executing", "waiting"):
        status, action, error, completed = rows[retired]
        assert status == "failed" and action is None and error and completed
    assert rows["done"] == ["completed", None, None, None]
    assert rows["other"] == ["pending", None, None, None]


def test_a_retired_run_finishes_its_queued_job_without_posting():
    """A failed run is terminal: its queued operator.run job returns before
    anything that could post to chat."""
    from app.services import operator
    db = Mock()
    db.get.return_value = SimpleNamespace(id="r1", workspace_id="w1", status="failed")
    job = SimpleNamespace(payload={"run_id": "r1"}, workspace_id="w1")
    with patch.object(operator, "_execute") as execute, patch.object(operator, "_post_result") as post:
        assert asyncio.run(operator.run_operator_job(job, db)) == {"run_id": "r1", "status": "failed"}
    execute.assert_not_called()
    post.assert_not_called()


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
