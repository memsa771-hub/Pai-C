"""Path research after the confirm gate (Task 3, fix round 1).

A finished explanation or program result is never thrown away. It is current
while the path-relevant part of the Vault (`vault_trigger_types` in
path_analyzer.json) is unchanged; otherwise it is still returned, marked
stale, and a new request re-runs it. Path research spends one allowance per
workspace and UTC day, and old budget keys are pruned. Fake models only.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import BackgroundJob, ExecutionRun, Workspace
from app.pai_c.paths.currency import current_relevance
from app.plugins._shared.budget import bounded_research, daily_key, spend
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import client_for
from tests.test_roadmap_engine import add_path, field_title

BACKEND = Path(__file__).resolve().parents[1]
HEADERS = {"X-Workspace-Token": "synthetic-test-only"}
DELEGATE = "app.research.gateway._delegate"
QUOTE = "VERBATIM-QUOTE-XYZ"


def accept(db, ws, kind, key, value):
    candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type=kind, key=key,
        proposed_value=value, confidence=0.9, source_type="user_explicit",
        evidence={"quote": QUOTE}, allow_user_explicit=True)
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()


def hobby(db, ws, text="Robotics"):
    accept(db, ws, "vault_item", "interest", {"text": text})


def city(db, ws, value="Lahore"):
    accept(db, ws, "vault_fact", "location.current_city", value)


# ---- the daily research budget -------------------------------------------------------

def test_two_vault_versions_on_one_day_share_one_allowance_and_a_new_day_starts_another():
    day = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "PAI_RESEARCH_MAX_CALLS_PER_STUDENT", 1):
        def attempt(now):
            with bounded_research(queries=5, fetches=5, seconds=30, workspace_id=student.workspace_id,
                                  budget_key=daily_key("path_research", now)):
                return spend("web.search")
        assert attempt(day) is None
        hobby(db, student.workspace_id)  # a new Vault version, the same day
        assert attempt(day + timedelta(hours=5)) == "research_student_budget_exceeded"
        assert attempt(day + timedelta(days=1)) is None


def test_path_research_takes_its_key_from_the_day_not_the_brief():
    for name in ("explain.py", "programs.py"):
        source = (BACKEND / "app/pai_c/paths" / name).read_text(encoding="utf-8")
        assert 'budget_key=daily_key("path_research")' in source, name
        assert "budget_key=brief" not in source, name


def test_old_budget_keys_are_pruned_when_spending():
    today = datetime.now(timezone.utc)
    old = daily_key("path_research", today - timedelta(days=8))
    recent = daily_key("path_research", today - timedelta(days=6))
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        workspace.settings = {**(workspace.settings or {}), "counselor_research_budgets": {
            old: 3, recent: 2, "1": 4, "0123456789abcdef": 5, "belief_checks:20389": 1}}
        db.commit()
        with bounded_research(queries=5, fetches=5, seconds=30, workspace_id=student.workspace_id,
                              budget_key=daily_key("path_research")):
            assert spend("web.search") is None
        db.expire_all()
        counters = db.get(Workspace, student.workspace_id).settings["counselor_research_budgets"]
    assert old not in counters and "1" not in counters and "0123456789abcdef" not in counters
    assert counters[recent] == 2 and counters["belief_checks:20389"] == 1
    assert counters[daily_key("path_research")] == 1


# ---- results stay current by relevance ----------------------------------------------

def explained(db, ws, row, *, try_it=None):
    run = ExecutionRun(workspace_id=ws, requested_by="pai", task_type="path_explain", objective="Explain",
                       status="completed",
                       constraints={"possibility_id": row.id, "relevance_version": current_relevance(db, ws)},
                       result={"capability_result": {"path": {"what_it_is": "A field", "try_it": try_it},
                                                     "facts": [], "missing": []}})
    db.add(run)
    db.commit()
    return run


def get_path(client, ws, row):
    response = client.get(f"/v1/counselor/paths/{row.id}", params={"network": ws}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_a_hobby_makes_the_explanation_stale_a_city_does_not_and_it_is_still_shown():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        row = add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        run = explained(db, ws, row)
        run_id = run.id
        client = client_for(student)
        try:
            data = get_path(client, ws, row)
            assert data["run_id"] == run.id and data["stale"] is False and data["path"]["what_it_is"] == "A field"
            city(db, ws)  # not path-relevant
            assert get_path(client, ws, row)["stale"] is False
            hobby(db, ws)  # interest is path-relevant
            data = get_path(client, ws, row)
        finally:
            app.dependency_overrides.pop(get_db, None)
    assert data["stale"] is True and data["run_id"] == run_id
    assert data["path"]["what_it_is"] == "A field"  # returned, not hidden
    assert data["status"] == "completed"


def test_explore_reruns_only_when_stale():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        row = add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        run = explained(db, ws, row)
        run_id, read = run.id, run.constraints["relevance_version"]
        client = client_for(student)
        url = f"/v1/counselor/paths/{row.id}/explore"
        queued = {"ok": True, "data": {"run_id": "new-run", "status": "pending"}}
        try:
            with patch(DELEGATE, AsyncMock(return_value=queued)) as sent:
                first = client.post(url, params={"network": ws}, headers=HEADERS)
                city(db, ws)
                second = client.post(url, params={"network": ws}, headers=HEADERS)
                assert sent.await_count == 0
                hobby(db, ws)
                third = client.post(url, params={"network": ws}, headers=HEADERS)
        finally:
            app.dependency_overrides.pop(get_db, None)
    assert first.json()["data"] == second.json()["data"] == {"run_id": run_id, "status": "completed", "resumed": True}
    assert third.json()["data"]["run_id"] == "new-run" and sent.await_count == 1
    constraints = sent.await_args.args[0]["constraints"]
    assert constraints["relevance_version"] != read
    assert f":relevance:{constraints['relevance_version']}" in constraints["research_key"]


def test_try_it_works_on_a_stale_explanation():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        JourneyService(db).ensure_counselor(ws)
        row = add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        explained(db, ws, row, try_it="Build a small circuit")
        hobby(db, ws)
        client = client_for(student)
        try:
            response = client.post(f"/v1/counselor/paths/{row.id}/try-it", params={"network": ws},
                                   headers=HEADERS, json={"accepted": True})
        finally:
            app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_programs_need_an_explanation_but_not_a_current_one():
    from app.research.gateway import request_research
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        journey = JourneyService(db).ensure_counselor(ws)
        row = add_path(student, db, field_title("electrical_engineering"), "electrical_engineering",
                       status="exploring")
        kwargs = dict(db=db, journey=JourneyService(db).get(ws, journey.id),
                      tool_context=SimpleNamespace(workspace_id=ws), possibility_id=row.id)
        queued = {"ok": True, "data": {"run_id": "programs", "status": "pending"}}
        with patch(DELEGATE, AsyncMock(return_value=queued)) as sent:
            assert await request_research("program_search", ws, **kwargs) is None
            explained(db, ws, row)
            hobby(db, ws)
            assert (await request_research("program_search", ws, **kwargs))["ok"]
        assert sent.await_args.args[0]["constraints"]["relevance_version"] == current_relevance(db, ws)


@pytest.mark.asyncio
async def test_a_stale_operator_result_is_still_explained_and_flagged():
    from app.services import operator
    with StudentSession() as student:
        with student.factory() as db:
            run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                               objective="Explain a path", status="completed",
                               constraints={"relevance_version": "an-older-vault"},
                               result={"final_message": "The explanation", "observations": []})
            db.add(run)
            db.commit()
            with patch("app.pai_c.orchestrator.handle_research_result",
                       AsyncMock(return_value="Here is what the field involves.")) as explain, \
                 patch("app.pai_c.posting.send_to_student", AsyncMock(return_value="event")) as post:
                await operator._post_result(db, student.workspace_id, "channel/pai-counselor", run.id,
                                             "completed", "Done.")
    explain.assert_awaited_once()
    assert post.await_args.args[4] == "Here is what the field involves."
    assert post.await_args.kwargs["metadata"]["stale"] is True
