"""The route decision and the roadmap HTTP API (spec ROADMAP_ENGINE_SPEC.md §1
Your route, §3, §5): one active decision per workspace, a snapshot of the
verdict at choose time, steps the student ticks, and the decision record PAI OS
reads at /v1/decision-records/current."""

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.main import app
from app.models import RouteDecision
from app.pai_c.roadmap.engine import roadmap_policy
from app.pai_c.roadmap.rules import rule_for, rules_as_of
from tests.test_roadmap_engine import add_education, add_path, field_title, fsc

ROOT = Path(__file__).resolve().parents[1]
TOKEN = {"X-Workspace-Token": "synthetic-test-only"}


@contextmanager
def roadmap_client(education=(), paths=()):
    from scripts.counselor_eval_support import StudentSession
    with StudentSession() as student:
        with student.factory() as db:
            for record in education:
                add_education(student, db, record)
            for key in paths:
                add_path(student, db, field_title(key), key)

        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            yield TestClient(app), student, {"network": student.workspace_id}
        finally:
            app.dependency_overrides.pop(get_db, None)


def pre_eng(percent=78):
    return roadmap_client([fsc("pre_engineering", percent)],
                          ["electrical_engineering", "computer_engineering", "mbbs"])


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


def choose(client, params, field_key):
    return client.post("/v1/roadmap/choose", params=params, headers=TOKEN, json={"field_key": field_key})


def test_get_roadmap_shape():
    with pre_eng() as (client, _, params):
        page = data(client.get("/v1/roadmap", params=params, headers=TOKEN))
    assert set(page) >= {"education_line", "counts", "fields", "chosen", "rules_as_of"}
    assert page["rules_as_of"] == rules_as_of() == "2026-10"  # the date the rules were checked
    assert page["counts"] == {"open": 2, "step": 0, "not_open": 1, "unknown": 0}
    card = page["fields"][0]
    assert set(card) >= {"possibility_id", "field_key", "title", "family", "why", "status", "verdict"}
    assert page["chosen"] is None


def test_auth_required():
    with pre_eng() as (client, _, params):
        assert client.get("/v1/roadmap", params=params).status_code == 401
        assert client.post("/v1/roadmap/choose", params=params,
                           json={"field_key": "electrical_engineering"}).status_code == 401
        assert client.post("/v1/roadmap/steps", params=params, json={"index": 0, "done": True}).status_code == 401
        assert client.post("/v1/roadmap/withdraw", params=params).status_code == 401
        assert client.get("/v1/decision-records/current", params=params).status_code == 401


def test_choose_open_field_writes_decision_with_route_steps():
    with pre_eng() as (client, student, params):
        decision = data(choose(client, params, "electrical_engineering"))
        page = data(client.get("/v1/roadmap", params=params, headers=TOKEN))
        current = data(client.get("/v1/decision-records/current", params=params, headers=TOKEN))
    rule = rule_for("electrical_engineering")
    assert decision["field_key"] == "electrical_engineering"
    assert decision["title"] == field_title("electrical_engineering")
    assert decision["live_status"] == "open" and decision["snapshot_verdict"]["status"] == "open"
    tests = [t.name for t in rule.tests_for("electrical_engineering")]
    # The full coloured route (FOUR_FEATURES_SPEC 4.1): an open field's group and marks are done.
    assert [step["key"] for step in decision["steps"]] == (
        ["group", "complete_intermediate", "marks"] + [f"test:{name}" for name in tests] + ["apply", "degree"])
    assert [step["status"] for step in decision["steps"][:3]] == ["done", "done", "done"]
    assert decision["steps"][-2]["values"] == {"degree": field_title("electrical_engineering")}
    assert decision["snapshot_steps"] == [{k: step[k] for k in ("key", "label_key", "values", "status")}
                                          for step in decision["steps"]]
    assert decision["steps_done"] == [] and decision["time"]["to_entry_months"] is not None
    assert decision["chosen_at"] and decision["possibility_id"]
    for step in decision["steps"]:
        assert step["label_key"] in roadmap_policy()["copy"]
    assert page["chosen"]["id"] == decision["id"] and page["chosen"]["live_status"] == "open"
    assert current["id"] == decision["id"] and current["workspace_id"] == student.workspace_id


def test_choose_step_field_lists_needs_first():
    with pre_eng(55) as (client, _, params):
        decision = data(choose(client, params, "electrical_engineering"))
    assert decision["snapshot_verdict"]["status"] == "step"
    marks = next(step for step in decision["steps"] if step["key"] == "marks")
    assert marks["status"] == "not" and marks["values"] == {"min": 60, "have": 55}
    assert [step["key"] for step in decision["steps"]][-2:] == ["apply", "degree"]


def test_choose_not_open_or_unknown_refused():
    with roadmap_client([fsc("pre_engineering", 78)], ["mbbs"]) as (client, student, params):
        with student.factory() as db:
            add_path(student, db, "Become a pilot", None, source="student")
        refused = choose(client, params, "mbbs")
        assert refused.status_code == 409 and "not open" in refused.text.lower()
        missing = choose(client, params, "civil_engineering")
        assert missing.status_code == 404
        with student.factory() as db:
            assert db.query(RouteDecision).count() == 0
    with roadmap_client([], ["electrical_engineering"]) as (client, _, params):
        unknown = choose(client, params, "electrical_engineering")
        assert unknown.status_code == 409 and "cannot check" in unknown.text.lower()


def test_choosing_another_withdraws_the_first():
    with pre_eng() as (client, student, params):
        first = data(choose(client, params, "electrical_engineering"))
        second = data(choose(client, params, "computer_engineering"))
        current = data(client.get("/v1/decision-records/current", params=params, headers=TOKEN))
        with student.factory() as db:
            rows = {row.id: row for row in db.query(RouteDecision).all()}
    assert current["id"] == second["id"]
    assert rows[first["id"]].withdrawn_at is not None and rows[second["id"]].withdrawn_at is None


def test_one_active_decision_per_workspace_enforced():
    with pre_eng() as (client, student, params):
        data(choose(client, params, "electrical_engineering"))
        with student.factory() as db:
            db.add(RouteDecision(workspace_id=student.workspace_id, field_key="computer_engineering",
                                 title="Computer", verdict={}, route={}, steps=[], steps_done=[]))
            with pytest.raises(IntegrityError):
                db.commit()


def test_steps_toggle_persists_and_validates_index():
    with pre_eng() as (client, _, params):
        assert client.post("/v1/roadmap/steps", params=params, headers=TOKEN,
                           json={"index": 0, "done": True}).status_code == 404
        decision = data(choose(client, params, "electrical_engineering"))
        ticked = data(client.post("/v1/roadmap/steps", params=params, headers=TOKEN,
                                  json={"key": "apply", "done": True}))
        assert ticked["steps_done"] == ["apply"]
        apply = next(step for step in ticked["steps"] if step["key"] == "apply")
        assert apply["status"] == "done" and apply["manual_done"] is True
        assert apply["evidence"]["source_label"] == roadmap_policy()["copy"]["marked_by_you"]
        # Older clients name the step by its position in the live steps.
        by_index = data(client.post("/v1/roadmap/steps", params=params, headers=TOKEN,
                                    json={"index": 0, "done": True}))
        assert by_index["steps_done"] == ["apply", decision["steps"][0]["key"]]
        page = data(client.get("/v1/roadmap", params=params, headers=TOKEN))
        assert page["chosen"]["steps_done"] == by_index["steps_done"]
        for body in ({"index": len(decision["steps"])}, {"index": -1}, {"key": "nope"}):
            bad = client.post("/v1/roadmap/steps", params=params, headers=TOKEN, json={**body, "done": True})
            assert bad.status_code == 422
        untick = data(client.post("/v1/roadmap/steps", params=params, headers=TOKEN,
                                  json={"key": "apply", "done": False}))
        assert untick["steps_done"] == [decision["steps"][0]["key"]]


def test_withdraw():
    with pre_eng() as (client, _, params):
        assert client.post("/v1/roadmap/withdraw", params=params, headers=TOKEN).status_code == 404
        decision = data(choose(client, params, "electrical_engineering"))
        withdrawn = data(client.post("/v1/roadmap/withdraw", params=params, headers=TOKEN))
        assert withdrawn["id"] == decision["id"] and withdrawn["withdrawn_at"]
        assert data(client.get("/v1/roadmap", params=params, headers=TOKEN))["chosen"] is None
        assert data(client.get("/v1/decision-records/current", params=params, headers=TOKEN)) is None


def _statuses(student):
    from app.models import PaiPossibility
    with student.factory() as db:
        return {row.study_field["key"]: row.status for row in db.query(PaiPossibility).all() if row.study_field}


def test_choose_marks_path_chosen_and_previous_back_to_saved():
    with pre_eng() as (client, student, params):
        data(choose(client, params, "electrical_engineering"))
        assert _statuses(student)["electrical_engineering"] == "chosen"
        data(choose(client, params, "computer_engineering"))
        statuses = _statuses(student)
    assert statuses["computer_engineering"] == "chosen"
    assert statuses["electrical_engineering"] == "saved"
    assert statuses["mbbs"] == "suggested"


def test_withdraw_puts_path_back_to_saved():
    with pre_eng() as (client, student, params):
        data(choose(client, params, "electrical_engineering"))
        data(client.post("/v1/roadmap/withdraw", params=params, headers=TOKEN))
        assert _statuses(student)["electrical_engineering"] == "saved"
        # The chosen path stays choosable after a withdraw.
        assert data(choose(client, params, "electrical_engineering"))["field_key"] == "electrical_engineering"


def test_chosen_status_is_not_a_student_transition():
    from app.pai_c.policy.controller import load_data
    transitions = load_data("possibilities.json")["transitions"]
    assert "choose" not in transitions and "chosen" not in transitions


@pytest.mark.asyncio
async def test_chosen_path_checkin_follows_the_active_decision():
    from app.models import BackgroundJob
    from app.pai_c.checkins import checkin_job
    with pre_eng() as (client, student, params):
        decision = data(choose(client, params, "electrical_engineering"))
        with student.factory() as db:
            job = db.query(BackgroundJob).filter(BackgroundJob.job_type == "counselor.checkin").one()
            assert job.payload == {"kind": "chosen_path", "reference_id": decision["id"]}
        data(client.post("/v1/roadmap/withdraw", params=params, headers=TOKEN))
        with student.factory() as db:
            job = db.query(BackgroundJob).filter(BackgroundJob.job_type == "counselor.checkin").one()
            assert (await checkin_job(job, db)) == {"status": "superseded"}


def test_decision_keeps_snapshot():
    with pre_eng() as (client, student, params):
        decision = data(choose(client, params, "electrical_engineering"))
        # The student corrects their marks below the floor: the page's live
        # verdict changes, the decision's snapshot stays what they chose.
        with student.factory() as db:
            add_education(student, db, fsc("pre_engineering", 50))
        page = data(client.get("/v1/roadmap", params=params, headers=TOKEN))
    chosen = page["chosen"]
    assert chosen["id"] == decision["id"]
    assert chosen["snapshot_verdict"]["status"] == "open" and chosen["live_status"] == "step"
    assert chosen["snapshot_steps"] == decision["snapshot_steps"]
    assert next(step for step in chosen["steps"] if step["key"] == "marks")["status"] == "not"


def test_live_status_unknown_when_path_gone():
    with pre_eng() as (client, student, params):
        decision = data(choose(client, params, "electrical_engineering"))
        with student.factory() as db:
            from app.models import PaiPossibility
            db.get(PaiPossibility, decision["possibility_id"]).status = "dismissed"
            db.commit()
        page = data(client.get("/v1/roadmap", params=params, headers=TOKEN))
    assert page["chosen"]["live_status"] == "unknown"


def test_migration_118_creates_route_decisions_and_downgrades():
    spec = importlib.util.spec_from_file_location("migration118", ROOT / "alembic/versions/118_route_decisions.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "118" and migration.down_revision == "117"
    with patch.object(migration, "op", Mock()) as op:
        migration.upgrade()
        name, *columns = op.create_table.call_args.args
        assert name == "pai_route_decisions"
        names = {column.name for column in columns if hasattr(column, "name")}
        assert names >= {"id", "workspace_id", "field_key", "possibility_id", "title", "verdict", "route",
                         "steps", "steps_done", "chosen_at", "withdrawn_at"}
        [index] = [call for call in op.create_index.call_args_list if call.kwargs.get("unique")]
        assert index.args[2] == ["workspace_id"]
        assert "withdrawn_at IS NULL" in str(index.kwargs["postgresql_where"])
        migration.downgrade()
        op.drop_table.assert_called_once_with("pai_route_decisions")
