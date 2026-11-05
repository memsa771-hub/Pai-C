"""The bridge delivers pending decision outbox rows right after a roadmap request commits, and the sweep delivers what
is still pending and catches students PAI OS is behind on (version compare). OS ports are stubbed (legacy suite)."""

import types
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import OsOutbox, RouteDecision
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
        got["held"] = max(got["held"] or 0, export["decision_version"])  # the OS now holds it
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


@pytest.mark.asyncio
async def test_sweep_resends_a_delivered_version_the_os_lacks(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(True):
            service = RouteDecisionService(db)
            service.choose(ws, "electrical_engineering", details=DETAILS)
            service.withdraw(ws)
            db.commit()
            bridge.deliver_pending(db, ws)
            assert [r.status for r in rows(db, ws)] == ["delivered", "delivered"]
            os_stub["submitted"].clear()
            os_stub["held"] = 1  # the OS lost v2
            bridge.sweep_once(db)
        assert [e["decision_version"] for e in os_stub["submitted"]] == [2]
        first, second = rows(db, ws)
        assert second.status == "delivered" and second.attempts == 0 and first.status == "delivered"


@pytest.mark.asyncio
async def test_sweep_leaves_not_sent_rows_alone(os_stub):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(True):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            (row,) = rows(db, ws)
            row.status, row.last_error = "not_sent", "incomplete"
            db.commit()
            bridge.sweep_once(db)
        assert rows(db, ws)[0].status == "not_sent" and os_stub["submitted"] == []


@pytest.mark.asyncio
async def test_one_students_error_does_not_stop_the_others(os_stub, monkeypatch):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(False):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        # student A: a second workspace's newest row, whose version lookup raises
        a_row = RouteDecision(id="a0000000-aaaa-4aaa-8aaa-aaaaaaaaaaaa", workspace_id=_second_workspace(db),
                              field_key="f", title="R", verdict={}, route={}, steps=[], steps_done=[],
                              decision_version=1, status="withdrawn")
        db.add(a_row)
        db.commit()
        bad = a_row.workspace_id

        def latest(ref):
            if ref == bad:
                raise RuntimeError("lookup failed")
            return None

        monkeypatch.setattr(plan_source, "latest_version", latest)
        with flag(True):
            bridge.sweep_once(db)
        assert [e["student_ref"] for e in os_stub["submitted"]] == [ws]
        assert rows(db, ws)[0].status == "delivered"


def _second_workspace(db) -> str:
    from app.models import Workspace
    w = Workspace(name="Second", password_hash="synthetic-test-only")
    db.add(w)
    db.commit()
    return str(w.id)


@pytest.mark.asyncio
async def test_escalations_still_delivered_when_decision_delivery_raises(os_stub, monkeypatch):
    async with confirmed_student() as (_, student, db, _j):
        calls = []
        monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", lambda limit=100: [object()])
        monkeypatch.setattr(bridge, "_deliver", lambda d: calls.append(1) or {"sent": 1})
        with flag(True), patch.object(bridge, "deliver_pending", side_effect=RuntimeError("x")):
            got = bridge.sweep_once(db)
        assert calls == [1] and got["sent"] == 1 and got["failed"] == 1


@pytest.mark.asyncio
async def test_module_off_answer_counts_as_delivered(os_stub, monkeypatch):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        monkeypatch.setattr(plan_source, "submit_decision", lambda export: "module_off")
        with flag(True):
            request(db, ws, lambda: RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS))
        (row,) = rows(db, ws)
        assert row.status == "delivered" and row.delivered_at is not None


@pytest.mark.asyncio
async def test_backfill_reset_clears_delivered_at(os_stub):
    """A delivered row the OS lacks goes back to pending with no delivery time (ledger deferred minor, T5)."""
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with flag(True):
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            bridge.deliver_pending(db, ws)
            assert rows(db, ws)[0].delivered_at is not None
            os_stub["held"] = None  # the OS lost v1
            bridge._backfill(db)
        (row,) = rows(db, ws)
        assert row.status == "pending" and row.delivered_at is None


# ---- Vault events (P1-T4, R-13) -----------------------------------------------------------------------------------

@pytest.fixture
def vault_stub(monkeypatch, os_stub):
    from app.os.ports import student_facts

    got = {"events": [], "raises": None, "held": None}

    def record(event):
        if got["raises"]:
            raise got["raises"]
        got["events"].append(event)
        got["held"] = max(got["held"] or 0, event["vault_version"])
        return "stored"

    monkeypatch.setattr(student_facts, "record_event", record)
    monkeypatch.setattr(student_facts, "latest_vault_version", lambda ref: got["held"])
    yield got


def facts_flag(value):
    return patch.object(config, "CONNECT_STUDENT_FACTS", value, create=True)


def vault_rows(db, ws):
    return [r for r in rows(db, ws) if r.kind == "vault_event"]


def vault_write(db, ws, province="punjab"):
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler

    c = MemoryCandidateService(db).propose(
        ws, "vault_item", key="domicile", proposed_value={"province": province}, confidence=0.9,
        source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
        evidence={"quote": "q", "capture": "details"})
    assert MemoryReconciler(db).reconcile(c).accepted
    db.commit()


@pytest.mark.asyncio
@pytest.mark.req("R-13")
async def test_vault_event_is_delivered_and_a_repeat_is_harmless(vault_stub):
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        with facts_flag(True):
            vault_write(db, ws)
            (row,) = vault_rows(db, ws)
            assert row.status == "pending"
            assert bridge.deliver_pending(db, ws) == {"delivered": 1, "failed": 0, "not_sent": 0}
            assert bridge.deliver_pending(db, ws) == {"delivered": 0, "failed": 0, "not_sent": 0}
        (row,) = vault_rows(db, ws)
        assert row.status == "delivered" and vault_stub["events"] == [row.payload]


@pytest.mark.asyncio
@pytest.mark.req("R-13")
async def test_os_down_keeps_the_vault_event_pending_and_the_sweep_delivers_it(vault_stub):
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        vault_stub["raises"] = ports.OsUnavailable()
        with facts_flag(True):
            vault_write(db, ws)
            bridge.deliver_pending(db, ws)
            (row,) = vault_rows(db, ws)
            assert row.status == "pending" and row.attempts == 0
            vault_stub["raises"] = None
            bridge.sweep_once(db)
        (row,) = vault_rows(db, ws)
        assert row.status == "delivered" and len(vault_stub["events"]) == 1


@pytest.mark.asyncio
@pytest.mark.req("R-13")
async def test_invalid_vault_event_is_not_sent(vault_stub):
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        with facts_flag(True):
            vault_write(db, ws)
            (row,) = vault_rows(db, ws)
            row.payload = {"schema": "pai.vault_event.v1"}
            db.commit()
            assert bridge.deliver_pending(db, ws) == {"delivered": 0, "failed": 0, "not_sent": 1}
        (row,) = vault_rows(db, ws)
        assert row.status == "not_sent" and row.last_error == "invalid_export" and vault_stub["events"] == []


@pytest.mark.asyncio
@pytest.mark.req("R-13")
async def test_sweep_backfills_the_newest_vault_version_with_every_key_since(vault_stub):
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        with facts_flag(True), patch("app.pai_c.connect.outbox.part_on", return_value=False):
            vault_write(db, ws, "punjab")  # the part was off: version counted, no event queued
            vault_write(db, ws, "sindh")
        assert vault_rows(db, ws) == []
        with facts_flag(True):
            bridge.sweep_once(db)
        (row,) = vault_rows(db, ws)
        assert row.status == "delivered" and row.payload["vault_version"] == 2
        assert row.payload["keys"] == ["constraint.domicile"] and vault_stub["held"] == 2
        with facts_flag(True):
            bridge.sweep_once(db)  # the OS now holds it: nothing more is queued
        assert len(vault_rows(db, ws)) == 1


@pytest.mark.asyncio
@pytest.mark.req("R-13")
async def test_flag_off_leaves_vault_events_alone(vault_stub):
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        with facts_flag(True):
            vault_write(db, ws)
        with facts_flag(False), flag(True):
            assert bridge.deliver_pending(db, ws) == {"delivered": 0, "failed": 0, "not_sent": 0}
        assert vault_stub["events"] == [] and vault_rows(db, ws)[0].status == "pending"
