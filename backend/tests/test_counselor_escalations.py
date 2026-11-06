from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient

from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import StudentJourney
from scripts.counselor_eval_support import StudentSession


def test_internal_escalation_preserves_history_and_queues_replan():
    with StudentSession() as student, student.factory() as db:
        service = JourneyService(db)
        journey = service.ensure_counselor(student.workspace_id)
        for stage in ("FOUNDATION", "DIRECTION", "MIRROR", "PROPOSED", "CHOSEN"):
            journey = service.set_counselor_stage(student.workspace_id, journey.id, stage,
                                                  validated_choice=stage == "CHOSEN")
        db.commit()

        def scoped_db():
            with student.factory() as session:
                yield session
        app.dependency_overrides[get_db] = scoped_db
        try:
            client = TestClient(app)
            body = {"workspace_id": student.workspace_id, "journey_id": journey.id,
                    "reason_type": "blocking_gap", "details": "Intake has closed"}
            with patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"):
                assert client.post("/v1/escalations", json=body).status_code == 401
                result = client.post("/v1/escalations", json=body,
                                     headers={"X-PAI-Service-Token": "local-test-token"})
                assert result.status_code == 200
            db.expire_all()
            row = db.get(StudentJourney, journey.id)
            assert row.current_stage == "DIRECTION"
            assert row.decisions[-1]["reason_type"] == "blocking_gap"
            assert row.next_recommended_action == {"type": "replan_discussion"}
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---- P1-T6 Task 4 (R-11): the five reasons, with CONNECT_HANDOFF on ----
from app.models import RouteDecision  # noqa: E402
from app.pai_c.connect.choice import ChoiceDetails  # noqa: E402
from app.pai_c.roadmap.decisions import RouteDecisionService  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from tests.test_choice_request_apply import DETAILS, OTHER  # noqa: E402
from tests.test_route_journey import TOKEN, choose, confirmed_student, stage, with_routes  # noqa: E402

FIVE = ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other")
SERVICE = {"X-PAI-Service-Token": "local-test-token"}
ESCALATION_STAGES = ("DIRECTION", "PROPOSED", "CHOSEN")


def handoff_on():
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch.object(config, "CONNECT_HANDOFF", True, create=True))
    stack.enter_context(patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"))
    stack.enter_context(patch("app.pai_os_bridge.counsellor_module_on", return_value=True))
    return stack


def post(client, student, journey_id, reason, **extra):
    body = {"workspace_id": student.workspace_id, "journey_id": journey_id, "reason_type": reason,
            "details": "A fixed note", **extra}
    return client.post("/v1/escalations", json=body, headers=SERVICE)


@pytest.mark.asyncio
@pytest.mark.req("R-11")
@pytest.mark.parametrize("reason", FIVE)
async def test_endpoint_accepts_five_reasons_when_on(reason):
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        with handoff_on():
            got = post(client, student, journey_id, reason, decision_version=1)
        assert got.status_code == 200, got.text
        db.expire_all()
        entry = db.get(StudentJourney, journey_id).decisions[-1]
        assert entry["kind"] == "route_escalation" and entry["reason_type"] == reason
        assert entry["decision_version"] == 1 and entry["previous_stage"] == "CHOSEN"
        assert got.json()["data"] == {"journey_id": journey_id, "stage": "PROPOSED"}


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_endpoint_needs_active_decision_when_on():
    async with confirmed_student() as (client, student, db, journey_id):
        with handoff_on():
            got = post(client, student, journey_id, "not_eligible")
        assert got.status_code == 409 and stage(db, journey_id) == "PROPOSED"
        assert not [d for d in db.get(StudentJourney, journey_id).decisions or [] if d["kind"] == "route_escalation"]


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_endpoint_works_outside_proposed_chosen_when_on():
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        JourneyService(db).set_counselor_stage(student.workspace_id, journey_id, "DIRECTION", replan_escalation=True)
        db.commit()
        with handoff_on():
            got = post(client, student, journey_id, "other")
        assert got.status_code == 200 and got.json()["data"]["stage"] == "DIRECTION"
        db.expire_all()
        entry = db.get(StudentJourney, journey_id).decisions[-1]
        assert entry["kind"] == "route_escalation" and entry["previous_stage"] == "DIRECTION"


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_chosen_goes_to_proposed_decision_kept():
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        db.expire_all()
        before = [(r.id, r.decision_version, r.withdrawn_at) for r in db.query(RouteDecision).all()]
        with handoff_on():
            assert post(client, student, journey_id, "all_rejected").status_code == 200
        db.expire_all()
        assert stage(db, journey_id) == "PROPOSED"
        assert [(r.id, r.decision_version, r.withdrawn_at) for r in db.query(RouteDecision).all()] == before
        assert RouteDecisionService(db).active(student.workspace_id) is not None


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_follow_active_does_not_bounce_after_escalation():
    from app.pai_c.journey_sync import sync_counselor_stage
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        with handoff_on():
            assert post(client, student, journey_id, "not_eligible").status_code == 200
        sync_counselor_stage(db, student.workspace_id, reason="student")
        db.commit()
        assert stage(db, journey_id) == "PROPOSED"  # not bounced back to CHOSEN
        choose(client, student, "computer_engineering")  # a new choice
        assert stage(db, journey_id) == "CHOSEN"


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_legacy_escalation_entry_does_not_hold_the_stage_back():
    """An entry without a decision version (flags off, or before this task) never blocks follow_active."""
    from app.pai_c.journey_sync import sync_counselor_stage
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        JourneyService(db).set_counselor_stage(student.workspace_id, journey_id, "PROPOSED")
        row = db.get(StudentJourney, journey_id)
        row.decisions = [*row.decisions, {"kind": "route_escalation", "reason_type": "blocking_gap"}]
        db.commit()
        sync_counselor_stage(db, student.workspace_id, reason="student")
        db.commit()
        assert stage(db, journey_id) == "CHOSEN"


def test_flags_off_422_is_byte_identical_to_the_pre_change_answers():
    """HANDOFF off: the whole 422 `detail` list (and the 503 for a request that validates) equals what the code before
    this task answered, captured at 542c354 for the same bodies (decision_version is an ignored extra field)."""
    import json
    from pathlib import Path
    expected = json.loads((Path(__file__).parent / "fixtures" / "connect" / "escalation_422_pre_change.json").read_text())
    client = TestClient(app)
    assert set(expected) >= {"foo", "not_eligible", "deadline_passed", "other", "not_eligible_short", "dv0"}
    app.dependency_overrides[get_db] = lambda: iter([None])  # no request here reaches the database
    try:
        with patch.object(config, "PAI_OS_SERVICE_TOKEN", ""):  # as when captured: a body that validates answers 503
            for name, case in expected.items():
                got = client.post("/v1/escalations", json=case["body"])
                assert (got.status_code, got.json()["detail"]) == (case["status"], case["detail"]), name
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.req("R-11")
def test_on_the_new_reasons_and_a_version_validate():
    from pydantic import ValidationError
    from app.routers.escalations import EscalationInput
    body = {"workspace_id": "w", "journey_id": "j", "reason_type": "other", "details": "A fixed note"}
    with handoff_on():
        assert EscalationInput(**body, decision_version=3).decision_version == 3
        for bad in ({"decision_version": 0}, {"reason_type": "foo"}):
            with pytest.raises(ValidationError):
                EscalationInput(**{**body, **bad})
    with patch.object(config, "CONNECT_HANDOFF", False, create=True):  # off: the version is ignored, the reason is not
        assert EscalationInput(**{**body, "reason_type": "blocking_gap"}, decision_version=0).decision_version is None
        with pytest.raises(ValidationError):
            EscalationInput(**body)


async def choose_with(db, student, field, details):
    """A choice with places (so two choices can differ), as the choice-request tests make it."""
    with patch("app.pai_os_bridge.route_supported", return_value=True), \
            patch("app.pai_c.connect.outbox.part_on", return_value=True):
        RouteDecisionService(db).choose(student.workspace_id, field, details=details)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_stale_escalation_is_refused_and_the_stage_stays():
    """An escalation made for a choice the student has since changed (or for a version that does not exist yet) is a
    409 and the journey does not move."""
    from app.pai_c.roadmap.decisions import RouteDecisionService
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        await choose_with(db, student, "electrical_engineering", DETAILS)  # version 1
        await choose_with(db, student, "computer_engineering", OTHER)  # version 2, other places
        with handoff_on():
            old = post(client, student, journey_id, "not_eligible", decision_version=1)
            future = post(client, student, journey_id, "not_eligible", decision_version=9)
            now = post(client, student, journey_id, "not_eligible", decision_version=2)
        assert old.status_code == 409 and future.status_code == 409 and now.status_code == 200
        db.expire_all()
        escalations = [d for d in db.get(StudentJourney, journey_id).decisions if d["kind"] == "route_escalation"]
        assert len(escalations) == 1 and escalations[0]["decision_version"] == 2
        assert RouteDecisionService(db).active(student.workspace_id).decision_version == 2


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_escalation_for_an_earlier_version_of_the_same_choice_is_taken():
    from app.pai_c.roadmap.decisions import RouteDecisionService
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        await choose_with(db, student, "electrical_engineering", DETAILS)
        RouteDecisionService(db).update_consent(student.workspace_id, authorized_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
        db.commit()
        with handoff_on():
            assert post(client, student, journey_id, "other", decision_version=1).status_code == 200


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_escalation_for_a_choice_whose_field_changed_is_refused():
    """The same places, route and intake under another field is another choice: the old escalation is stale."""
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        await choose_with(db, student, "electrical_engineering", DETAILS)  # version 1
        await choose_with(db, student, "computer_engineering", DETAILS)  # version 2, same places, other field
        with handoff_on():
            assert post(client, student, journey_id, "not_eligible", decision_version=1).status_code == 409


async def _escalated(client, student, db, journey_id):
    with_routes(student, db)
    await choose_with(db, student, "electrical_engineering", DETAILS)
    with handoff_on():
        assert post(client, student, journey_id, "not_eligible").status_code == 200
    assert stage(db, journey_id) == "PROPOSED"


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_consent_copy_after_escalation_does_not_bounce_the_stage():
    from app.pai_c.journey_sync import sync_counselor_stage
    async with confirmed_student() as (client, student, db, journey_id):
        await _escalated(client, student, db, journey_id)
        RouteDecisionService(db).update_consent(student.workspace_id, authorized_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
        db.commit()
        assert RouteDecisionService(db).active(student.workspace_id).decision_version == 2
        sync_counselor_stage(db, student.workspace_id, reason="student")
        db.commit()
        assert stage(db, journey_id) == "PROPOSED"


@pytest.mark.asyncio
@pytest.mark.req("R-11")
async def test_choice_request_with_new_places_after_escalation_returns_to_chosen():
    from app.pai_c.journey_sync import sync_counselor_stage
    async with confirmed_student() as (client, student, db, journey_id):
        await _escalated(client, student, db, journey_id)
        request = {"schema": "pai.choice_request.v1", "key": "choice_request:7", "student_ref": "x", "journey_id": "j",
                   "proposal_id": 7, "based_on_version": 1,
                   "programmes": [{"programme_ref": "uni-a:cs", "rank": 1}], "target_intake": None,
                   "requested_at": "2026-11-06T10:00:00Z"}
        with patch("app.pai_os_bridge.route_supported", return_value=True), \
                patch("app.pai_c.connect.outbox.part_on", return_value=True):
            assert RouteDecisionService(db).apply_choice_request(student.workspace_id, request) == ("written", 2)
        db.commit()
        sync_counselor_stage(db, student.workspace_id, reason="student")
        db.commit()
        assert stage(db, journey_id) == "CHOSEN"


@pytest.mark.asyncio
@pytest.mark.req("R-11")
@pytest.mark.parametrize("reason", ("not_eligible", "deadline_passed", "other"))
async def test_flags_off_new_reasons_are_the_same_422(reason):
    """HANDOFF off: the endpoint takes the three reasons it took before; any other is today's 422."""
    async with confirmed_student() as (client, student, db, journey_id):
        with patch.object(config, "PAI_OS_SERVICE_TOKEN", "local-test-token"):
            got = post(client, student, journey_id, reason)
        assert got.status_code == 422
        (first,) = got.json()["detail"][:1]
        assert first["type"] == "literal_error" and first["loc"] == ["body", "reason_type"]
        assert stage(db, journey_id) == "PROPOSED"
