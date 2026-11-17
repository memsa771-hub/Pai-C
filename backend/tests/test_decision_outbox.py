"""The decision export v2 and its outbox row, written in the same transaction as the decision."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import OsOutbox, RouteDecision, StudentJourney
from app.pai_c.connect import outbox
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.os_export import decision_record_v2
from app.pai_c.roadmap.decisions import RouteDecisionService
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = [pytest.mark.req("R-03"), pytest.mark.req("R-79")]

DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1), ("uni-b:cs", 2)), intake=("autumn", 2027))


def items(db, workspace_id):
    db.expire_all()
    return list(db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == workspace_id)
                           .order_by(OsOutbox.key)))


def on():
    return patch("app.pai_c.connect.outbox.part_on", return_value=True)


@pytest.mark.asyncio
async def test_no_outbox_when_flag_off():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering", details=DETAILS)
        service.withdraw(student.workspace_id)
        db.commit()
        assert items(db, student.workspace_id) == []
        assert outbox.record(db, service.newest(student.workspace_id)) is None


@pytest.mark.asyncio
async def test_outbox_row_in_same_transaction():
    async with confirmed_student() as (_, student, db, journey_id):
        with_routes(student, db)
        ws = student.workspace_id
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.rollback()
            assert items(db, ws) == [] and db.scalars(select(RouteDecision).where(
                RouteDecision.workspace_id == ws)).first() is None
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        (row,) = items(db, ws)
        assert row.key == f"decision:{ws}:1" and row.status == "pending" and row.last_error is None
        payload = row.payload
        assert payload["schema"] == "pai.decision_record.v2" and payload["decision_version"] == 1
        assert payload["status"] == "chosen" and payload["journey_id"] == journey_id
        assert payload["student_ref"] == ws and payload["origin_country"] == "PK"
        assert payload["target_intake"] == {"term": "autumn", "year": 2027}
        assert payload["programmes"] == [{"programme_ref": "uni-a:cs", "rank": 1},
                                         {"programme_ref": "uni-b:cs", "rank": 2}]
        assert payload["chosen_at"].endswith("+00:00")
        from app.os.contracts.decision_record_v2 import DecisionRecordV2
        DecisionRecordV2.model_validate(payload)
        assert [i.key for i in outbox.pending_for(db, ws)] == [row.key]
        assert outbox.pending_for(db, "other") == []


@pytest.mark.asyncio
async def test_withdraw_writes_a_withdrawn_export():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            service.withdraw(ws)
            db.commit()
        first, second = items(db, ws)
        assert second.key == f"decision:{ws}:2" and second.status == "pending"
        assert second.payload["status"] == "withdrawn" and second.payload["programmes"] == []
        assert second.payload["decision_version"] == 2 and second.payload["target_intake"] is None
        assert second.payload["os_supported"] is True
        from app.os.contracts.decision_record_v2 import DecisionRecordV2
        DecisionRecordV2.model_validate(second.payload)


@pytest.mark.asyncio
async def test_unsupported_route_is_not_sent():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=False):
            RouteDecisionService(db).choose(student.workspace_id, "electrical_engineering", details=DETAILS)
            db.commit()
        (row,) = items(db, student.workspace_id)
        assert row.status == "not_sent" and row.last_error == "not_supported"
        assert outbox.pending_for(db) == []


@pytest.mark.asyncio
async def test_choose_without_details_is_not_sent():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        with on():
            RouteDecisionService(db).choose(student.workspace_id, "electrical_engineering")
            db.commit()
        (row,) = items(db, student.workspace_id)
        assert row.status == "not_sent" and row.last_error == "not_supported"


@pytest.mark.asyncio
async def test_no_journey_is_not_sent():
    async with confirmed_student() as (_, student, db, journey_id):
        with_routes(student, db)
        db.get(StudentJourney, journey_id).status = "paused"
        db.commit()
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service = RouteDecisionService(db)
            service.choose(student.workspace_id, "electrical_engineering", details=DETAILS)
            db.commit()
            assert decision_record_v2(db, service.newest(student.workspace_id)) is None
        (row,) = items(db, student.workspace_id)
        assert row.status == "not_sent" and row.last_error == "no_journey" and row.payload is None


@pytest.mark.asyncio
async def test_supported_but_incomplete_is_not_sent():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        bare = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor", places=(), intake=None)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            RouteDecisionService(db).choose(student.workspace_id, "electrical_engineering", details=bare)
            db.commit()
        (row,) = items(db, student.workspace_id)
        assert row.status == "not_sent" and row.last_error == "incomplete"


@pytest.mark.asyncio
@pytest.mark.req("R-06")
async def test_move_to_unsupported_after_a_delivery_is_sent():
    """Final review I3: after a version reached the OS, a change to a route the OS cannot run is still sent, so the
    OS closes the old plan (rows 6.3, 6.14)."""
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        (first,) = items(db, ws)
        first.status = "delivered"
        db.commit()
        with on(), patch("app.pai_os_bridge.route_supported", return_value=False):
            service.choose(ws, "computer_engineering", details=DETAILS)
            db.commit()
        _, second = items(db, ws)
        assert second.key == f"decision:{ws}:2" and second.status == "pending" and second.last_error is None
        assert second.payload["os_supported"] is False and second.payload["status"] == "chosen"
        from app.os.contracts.decision_record_v2 import DecisionRecordV2
        DecisionRecordV2.model_validate(second.payload)


@pytest.mark.asyncio
async def test_move_to_unsupported_while_the_earlier_version_is_pending_is_sent():
    """D-k 2: an earlier version still pending counts like a delivered one (it will arrive and open a plan), so the
    move to an unsupported route is sent too. Only when nothing is delivered or pending does it stay not_sent
    (test_not_sent_earlier_version_does_not_count in test_consent_versions.py)."""
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        with on(), patch("app.pai_os_bridge.route_supported", return_value=False):
            service.choose(ws, "computer_engineering", details=DETAILS)
            db.commit()
        first, second = items(db, ws)
        assert first.status == "pending"
        assert second.status == "pending" and second.last_error is None


@pytest.mark.asyncio
async def test_incomplete_after_a_delivery_stays_not_sent():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        bare = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor", places=(), intake=None)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            (first,) = items(db, ws)
            first.status = "delivered"
            db.commit()
            service.choose(ws, "computer_engineering", details=bare)
            db.commit()
        _, second = items(db, ws)
        assert second.status == "not_sent" and second.last_error == "incomplete"
