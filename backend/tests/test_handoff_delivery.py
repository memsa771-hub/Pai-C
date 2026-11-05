"""The bridge delivers pending decision outbox rows right after a roadmap request commits, and the sweep delivers what
is still pending and catches students PAI OS is behind on (version compare). OS ports are stubbed (legacy suite)."""

import types
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import OsOutbox
from app.os import ports
from app.os.ports import escalation as os_escalation
from app.os.ports import plan_source
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionService
from app.routers import roadmap
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = [pytest.mark.req("R-03"), pytest.mark.req("R-12")]

DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1),), intake=("autumn", 2027))


@pytest.fixture
def os_stub(monkeypatch):
    got = {"submitted": [], "held": None, "raises": None}

    def submit(export):
        if got["raises"]:
            raise got["raises"]
        got["submitted"].append(export)
        return "stored"

    monkeypatch.setattr(plan_source, "counsellor_enabled", lambda: True)
    monkeypatch.setattr(plan_source, "submit_decision", submit)
    monkeypatch.setattr(plan_source, "latest_version", lambda ref: got["held"])
    monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", lambda limit=100: [])
    monkeypatch.setattr(bridge, "route_supported", lambda *a: True)
    ports.configure(types.SimpleNamespace())
    yield got
    ports.configure(None)


def flag(value):
    return patch.object(config, "CONNECT_HANDOFF", value, create=True)


def rows(db, ws):
    db.expire_all()
    return list(db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == ws).order_by(OsOutbox.key)))


def request(db, ws, action):
    """A roadmap write as the router runs it."""
    return roadmap._write(action, db, ws)


@pytest.mark.asyncio
async def test_choose_delivers_immediately(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(True):
            request(db, ws, lambda: RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS))
        assert [e["decision_version"] for e in os_stub["submitted"]] == [1]
        (row,) = rows(db, ws)
        assert row.status == "delivered" and row.delivered_at is not None and row.payload == os_stub["submitted"][0]


@pytest.mark.asyncio
async def test_os_down_keeps_row_pending(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        os_stub["raises"] = ports.OsUnavailable()
        with flag(True):
            request(db, ws, lambda: RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS))
            (row,) = rows(db, ws)
            assert row.status == "pending" and row.attempts == 0
            os_stub["raises"] = None
            bridge.sweep_once(db)
        (row,) = rows(db, ws)
        assert row.status == "delivered" and len(os_stub["submitted"]) == 1


@pytest.mark.asyncio
async def test_delivery_error_counts_attempts(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        os_stub["raises"] = RuntimeError("boom with student data")
        with flag(True):
            request(db, ws, lambda: RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS))
        (row,) = rows(db, ws)
        assert row.status == "pending" and row.attempts == 1 and row.last_error == "RuntimeError"


@pytest.mark.asyncio
async def test_invalid_payload_is_not_sent(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(True):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            (row,) = rows(db, ws)
            row.payload = {"schema": "pai.decision_record.v2"}
            db.commit()
            assert bridge.deliver_pending(db, ws) == {"delivered": 0, "failed": 0, "not_sent": 1}
        (row,) = rows(db, ws)
        assert row.status == "not_sent" and row.last_error == "invalid_export" and os_stub["submitted"] == []


@pytest.mark.asyncio
async def test_sweep_backfills_newest_only(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(False):
            service = RouteDecisionService(db)
            service.choose(ws, "electrical_engineering", details=DETAILS)
            service.withdraw(ws)
            db.commit()
        assert rows(db, ws) == []
        with flag(True):
            bridge.sweep_once(db)
            (row,) = rows(db, ws)
            assert row.key == f"decision:{ws}:2" and row.status == "delivered"
            assert [e["decision_version"] for e in os_stub["submitted"]] == [2]
            bridge.sweep_once(db)
        assert len(os_stub["submitted"]) == 1


@pytest.mark.asyncio
async def test_sweep_skips_a_student_the_os_is_not_behind_on(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(False):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        os_stub["held"] = 1
        with flag(True):
            bridge.sweep_once(db)
        assert rows(db, ws) == [] and os_stub["submitted"] == []


@pytest.mark.asyncio
async def test_flag_off_sweep_sends_nothing(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(False):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            bridge.sweep_once(db)
            assert bridge.deliver_pending(db) == {"delivered": 0, "failed": 0, "not_sent": 0}
        assert rows(db, ws) == [] and os_stub["submitted"] == []


@pytest.mark.asyncio
async def test_a_failing_bridge_never_fails_the_request(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(True), patch.object(bridge, "deliver_pending", side_effect=RuntimeError("down")):
            out = request(db, ws, lambda: RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS))
        assert out is not None and rows(db, ws)[0].status == "pending"
