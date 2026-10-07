"""Roadmap choice remains a validated student action, separate from content."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.journey import JourneyService
from app.models import DecisionRecord, ExecutionRun, NotificationRecord, Roadmap, RoadmapStudentState, StudentJourney
from app.roadmaps.service import RoadmapError, RoadmapService
from scripts.counselor_eval_support import StudentSession


def _journey(db, workspace_id):
    journeys = JourneyService(db)
    journey = journeys.ensure_counselor(workspace_id)
    for stage in ("FOUNDATION", "DIRECTION", "RESEARCHING", "ASSESSING", "PROPOSED"):
        journey = journeys.set_counselor_stage(workspace_id, journey.id, stage)
    return journey


def _card(db, workspace_id, journey_id, title):
    roadmap = Roadmap(workspace_id=workspace_id, journey_id=journey_id,
                      origin="alternative", title=title,
                      route={"country": "Germany"}, generation_status="ready",
                      sources=[{"url": "https://example.edu/route", "checked_at": "2026-10-06"}])
    db.add(roadmap)
    db.flush()
    db.add(RoadmapStudentState(roadmap_id=roadmap.id, journey_id=journey_id))
    db.flush()
    return roadmap


def test_student_actions_preserve_content_and_validate_presented_choice():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        first = _card(db, student.workspace_id, journey.id, "CS pathway")
        second = _card(db, student.workspace_id, journey.id, "Another route")
        service = RoadmapService(db)
        assert len(service.list(student.workspace_id)) == 2
        with pytest.raises(RoadmapError, match="presented"):
            service.choose(student.workspace_id, first.id,
                           service.choice_token(first, "test-secret"), "test-secret")
        service.list(student.workspace_id, presented=True)
        service.set_flag(student.workspace_id, first.id, "favorite", True)
        service.set_flag(student.workspace_id, second.id, "exploring", True)
        service.focus(student.workspace_id, second.id)
        assert service.focused(student.workspace_id)["id"] == second.id
        service.dismiss(student.workspace_id, second.id, True)
        assert service.focused(student.workspace_id) is None
        assert len(service.list(student.workspace_id, "dismissed")) == 1
        service.dismiss(student.workspace_id, second.id, False)
        with pytest.raises(RoadmapError, match="confirmation"):
            service.choose(student.workspace_id, first.id, "bad-token", "test-secret")
        chosen = service.choose(student.workspace_id, first.id,
                                service.choice_token(first, "test-secret"), "test-secret")
        assert chosen["chosen_at"]
        assert service.get(student.workspace_id, first.id)["title"] == "CS pathway"
        assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "CHOSEN"
        decision = RoadmapService(db).current_decision(student.workspace_id)
        assert decision["roadmap_id"] == first.id
        assert decision["roadmap_version"] == first.version
        assert decision["choice_channel"] == "roadmaps"
        assert decision["assumptions"] == ["Earlier goal summary was not recorded"]
        with pytest.raises(RoadmapError, match="Counselor"):
            service.choose(student.workspace_id, second.id,
                           service.choice_token(second, "test-secret"), "test-secret")
        db.commit()


def test_choice_snapshots_confirmed_objective_gaps_and_risks():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        row = db.get(StudentJourney, journey.id)
        row.counselor_summary_draft = {"status": "confirmed", "summary": {
            "stated_goal": {"value": "Computer science", "status": "answered"},
            "envisioned_outcome": {"value": "Build accessible software", "status": "answered"}}}
        card = _card(db, student.workspace_id, journey.id, "CS pathway")
        card.gaps = [{"status": "fixable", "field": "test.english", "reason": "Retake"},
                     {"status": "met", "field": "education.level"}]
        card.risks = ["Fee may change"]
        service = RoadmapService(db)
        service.list(student.workspace_id, presented=True)
        service.choose(student.workspace_id, card.id,
                       service.choice_token(card, "test-secret"), "test-secret",
                       choice_channel="voice")
        record = db.query(DecisionRecord).one()
        assert record.real_objective == "Build accessible software"
        assert record.choice_channel == "voice"
        assert record.accepted_gaps == [card.gaps[0]]
        assert record.accepted_risks == ["Fee may change"]
        assert record.assumptions == []


def test_custom_card_is_idempotent_for_same_reconciled_goal():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        service = RoadmapService(db)
        first = service.create_custom(student.workspace_id, journey.id, "goal-id", "My own route", {})
        second = service.create_custom(student.workspace_id, journey.id, "goal-id", "My own route", {})
        assert first["id"] == second["id"]
        assert first["generation_status"] == "generating"


def test_profile_change_marks_fit_stale_without_erasing_student_state():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        card = _card(db, student.workspace_id, journey.id, "CS route")
        service = RoadmapService(db)
        service.set_flag(student.workspace_id, card.id, "favorite", True)
        assert service.mark_stale(student.workspace_id, "Student profile changed: education") == 1
        result = service.get(student.workspace_id, card.id)
        assert result["generation_status"] == "stale"
        assert result["stale_reason"] == "Student profile changed: education"
        assert result["favorite"] is True
        assert db.query(NotificationRecord).filter_by(
            workspace_id=student.workspace_id,
            dedupe_key=f"roadmap-stale:{card.id}:{card.version}").count() == 1
        service.list(student.workspace_id, presented=True)
        with pytest.raises(RoadmapError, match="ready"):
            service.choose(student.workspace_id, card.id,
                           service.choice_token(card, "test-secret"), "test-secret")


def test_rethink_returns_to_direction_and_preserves_the_presented_route():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        card = _card(db, student.workspace_id, journey.id, "CS route")
        result = RoadmapService(db).rethink(student.workspace_id, card.id)
        assert result["id"] == card.id
        refreshed = JourneyService(db).get(student.workspace_id, journey.id)
        assert refreshed.current_stage == "DIRECTION"
        assert any(item["kind"] == "roadmap_rethink" for item in refreshed.decisions)


def test_refreshed_research_updates_same_card_and_keeps_favorite():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        candidate = {"title": "CS route", "origin": "stated_goal",
                     "route": {"url": "https://example.edu/cs"},
                     "sources": [{"url": "https://example.edu/cs", "checked_at": "2026-10-06"}],
                     "gaps": []}
        def run_for(key):
            row = ExecutionRun(workspace_id=student.workspace_id,
                               requested_by="openagents:pai", objective="Research",
                               task_type="roadmap_research", status="completed",
                               constraints={"research_key": f"{journey.id}:{key}"},
                               result={"capability_result": {"roadmaps": [candidate]}})
            db.add(row)
            db.flush()
            return row
        service = RoadmapService(db)
        first = service.publish_from_run(run_for("original"))[0]
        service.set_flag(student.workspace_id, first, "favorite", True)
        assert service.mark_stale(student.workspace_id, "Student profile changed") == 1
        second = service.publish_from_run(run_for("refresh"))[0]
        assert first == second
        restored = service.get(student.workspace_id, first)
        assert restored["generation_status"] == "ready"
        assert restored["stale_reason"] is None
        assert restored["favorite"] is True
        assert restored["version"] == 2
        assert db.query(NotificationRecord).filter_by(
            workspace_id=student.workspace_id,
            dedupe_key=f"roadmap-ready:{first}:2").one().title == "Roadmap refreshed"


def test_missing_search_result_keeps_a_failed_stated_goal_card():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        run = ExecutionRun(workspace_id=student.workspace_id,
                           requested_by="openagents:pai", objective="Research",
                           task_type="roadmap_research", status="completed",
                           constraints={"research_key": f"{journey.id}:goal",
                                        "capability_input": {"brief": {
                                            "stated_preference": "Architecture abroad",
                                            "country": "Germany"}}},
                           result={"capability_result": {"roadmaps": [], "unconfirmed": [
                               {"reason": "Search provider unavailable"}]}})
        db.add(run)
        db.flush()
        published = RoadmapService(db).publish_from_run(run)
        assert len(published) == 1
        card = RoadmapService(db).get(student.workspace_id, published[0])
        assert card["origin"] == "stated_goal"
        assert card["generation_status"] == "failed"
        assert card["stale_reason"] == "Search provider unavailable"
        assert card["sources"] == []


def test_failed_route_retry_reuses_its_brief_and_preserves_origin():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        card = _card(db, student.workspace_id, journey.id, "CS alternative")
        card.generation_status = "failed"
        card.route = {"url": "https://example.edu/cs", "country": "Germany"}
        old = ExecutionRun(workspace_id=student.workspace_id,
                           requested_by="openagents:pai", objective="Research CS",
                           task_type="roadmap_research", status="failed",
                           constraints={"research_key": f"{journey.id}:goal",
                                        "capability_input": {"brief": {
                                            "stated_preference": "CS in Germany",
                                            "underlying_objective": "tech career",
                                            "country": "Germany"}}})
        db.add(old)
        db.flush()
        card.execution_run_id = old.id
        objective, constraints = RoadmapService(db).prepare_retry(student.workspace_id, card.id)
        assert objective == "Research CS"
        assert constraints["research_key"] != old.constraints["research_key"]
        assert "refresh_candidate" not in old.constraints["capability_input"]["brief"]
        assert constraints["capability_input"]["brief"]["refresh_candidate"]["origin"] == "alternative"
        assert card.generation_status == "generating"
        assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "RESEARCHING"
        with pytest.raises(RoadmapError, match="Only failed or stale"):
            RoadmapService(db).prepare_retry(student.workspace_id, card.id)


def test_roadmap_api_is_workspace_scoped_and_choice_requires_presentation():
    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        card = _card(db, student.workspace_id, journey.id, "CS route")
        db.commit()
        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            client = TestClient(app)
            url = f"/v1/roadmaps/{card.id}"
            params = {"network": student.workspace_id}
            headers = {"X-Workspace-Token": "synthetic-test-only"}
            assert client.get("/v1/roadmaps", params=params).status_code == 401
            assert client.post(url + "/choice-token", params=params, headers=headers).status_code == 409
            response = client.get("/v1/roadmaps", params=params, headers=headers)
            assert response.status_code == 200
            assert response.json()["data"]["roadmaps"][0]["id"] == card.id
            with patch("app.counseling.core.CounselorModelProvider.respond",
                       AsyncMock(return_value="Which part of this route matters most to you?")), \
                    patch("app.counseling.runtime._post_response", AsyncMock(return_value="event-1")) as posted:
                focused = client.post(url + "/focus", params=params, headers=headers)
                assert focused.status_code == 200
                assert posted.await_args.args[2] == "channel/pai-counselor"
            token = client.post(url + "/choice-token", params=params, headers=headers)
            assert token.status_code == 200
            chosen = client.post(url + "/choose", params=params, headers=headers,
                                 json={"confirm_token": token.json()["data"]["confirm_token"]})
            assert chosen.status_code == 200
            assert chosen.json()["data"]["chosen_at"]
            decision = client.get("/v1/decision-records/current", params=params, headers=headers)
            assert decision.status_code == 200
            assert decision.json()["data"]["roadmap_id"] == card.id
        finally:
            app.dependency_overrides.pop(get_db, None)
