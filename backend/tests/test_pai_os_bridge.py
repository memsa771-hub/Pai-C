"""Slice 8 Task 8: the glue between the Counsellor and PAI OS (PAI OS Slice 8 spec §2.7). Host code. The OS ports are
stubbed here (the legacy suite has no OS database); the Counsellor's escalation code is the real one. Fictional."""

import os
import types
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app import pai_os_bridge as bridge
from app.config import config
from app.journey import JourneyService
from app.models import RouteDecision, StudentJourney
from app.os import ports
from app.os.contracts.escalation import EscalationV1
from app.os.ports import escalation as os_escalation
from app.os.ports import plan_source
from scripts.counselor_eval_support import StudentSession

T0 = datetime(2027, 1, 10, 4, 0, tzinfo=timezone.utc)
TOKEN = "local-test-token"


@pytest.fixture
def student():
    with StudentSession() as s:
        yield s


@pytest.fixture
def os_stub(monkeypatch):
    """The OS ports, recorded: mounted, the module on; escalations pending and their delivery marks."""
    got = {"marked": [], "pending": [], "event_types": {}}
    monkeypatch.setattr(plan_source, "counsellor_enabled", lambda: True, raising=False)
    monkeypatch.setattr(os_escalation, "event_type_of", lambda key: got["event_types"].get(key), raising=False)
    monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", lambda limit=100: list(got["pending"]))
    monkeypatch.setattr(os_escalation, "mark_counsellor_delivery",
                        lambda key, status, reason=None: got["marked"].append((key, status, reason)))
    ports.configure(types.SimpleNamespace())  # mounted (the stubs above answer instead of the real services)
    yield got
    ports.configure(None)


def journey_at(student, stage: str) -> str:
    with student.factory() as db:
        service = JourneyService(db)
        journey = service.ensure_counselor(student.workspace_id)
        # Merge pai-c + pai-os: pai-c's stage machine goes MIRROR -> PROPOSED (RESEARCHING / ASSESSING are only
        # for old data now, app/pai_c/stages.py).
        for s in ("FOUNDATION", "DIRECTION", "MIRROR", "PROPOSED", "CHOSEN"):
            journey = service.set_counselor_stage(student.workspace_id, journey.id, s,
                                                  validated_choice=s == "CHOSEN")
            if s == stage:
                break
        db.commit()
        return journey.id


def escalation(student, journey_id: str, reason: str = "blocking_gap", key: str = "escalation:7") -> EscalationV1:
    return EscalationV1(key=key, case_id=7, journey_id=journey_id, student_ref=student.workspace_id, reason=reason,
                        note="A required step is blocked and the plan cannot fix it alone.", raised_at=T0)


@pytest.mark.parametrize("reason,sent_as", [("blocking_gap", "blocking_gap"), ("all_rejected", "all_rejected"),
                                            ("not_eligible", "route_not_possible"),
                                            ("deadline_passed", "route_not_possible"), ("other", "route_not_possible")])
def test_escalation_reaches_counsellor_endpoint(student, os_stub, reason, sent_as):
    journey_id = journey_at(student, "CHOSEN")
    os_stub["pending"] = [escalation(student, journey_id, reason)]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["sent"] == 1 and os_stub["marked"] == [("escalation:7", "sent", None)]
    with student.factory() as db:
        row = db.get(StudentJourney, journey_id)
        assert row.current_stage == "DIRECTION"  # the Counsellor takes the student back to choosing
        assert row.decisions[-1]["reason_type"] == sent_as
        assert row.decisions[-1]["details"].startswith("A required step")


def test_counsellor_409_marks_refused(student, os_stub):
    journey_id = journey_at(student, "MIRROR")  # not at a route decision
    os_stub["pending"] = [escalation(student, journey_id)]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["refused"] == 1 and os_stub["marked"] == [("escalation:7", "refused", "HTTP 409")]


def test_unknown_journey_marks_refused(student, os_stub):
    os_stub["pending"] = [escalation(student, "no-such-journey")]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), student.factory() as db:
        bridge.sweep_once(db)
    assert os_stub["marked"] == [("escalation:7", "refused", "HTTP 404")]


def test_no_token_leaves_pending(student, os_stub):
    os_stub["pending"] = [escalation(student, journey_at(student, "CHOSEN"))]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", ""), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["waiting"] == 1 and os_stub["marked"] == []  # tried again on the next sweep


def test_os_not_mounted_noop(student):
    ports.configure(None)
    with student.factory() as db:
        assert bridge.sweep_once(db) == {"mounted": False}
        assert bridge.deliver_pending(db) == {"delivered": 0, "failed": 0, "not_sent": 0}


@pytest.mark.skipif(not os.environ.get("OS_TEST_DATABASE_URL"), reason="needs the PAI OS test database")
def test_module_off_by_default_end_to_end(student):
    """With the real PAI OS (module row as os_0013 leaves it): the export is stored and waits; nothing is sent."""
    from sqlalchemy import create_engine, select

    from app.os import models
    from app.os.api.services import make_services
    from app.os.settings import load_settings
    from tests.os.conftest import run_alembic, truncate_os_tables

    url = os.environ["OS_TEST_DATABASE_URL"]
    run_alembic(["upgrade", "os@head"], url)
    engine = create_engine(url)
    truncate_os_tables(engine)
    with engine.begin() as conn:
        conn.execute(models.modules.insert().values(module="counsellor", tenant_id="pai", enabled=False))
    ports.configure(make_services(load_settings({"OS_DATABASE_URL": url}), engine=engine))
    try:
        with student.factory() as db:
            export = {"decision_id": "d-1", "journey_id": "j-1", "student_ref": student.workspace_id,
                      "chosen_at": T0.isoformat(), "decision_version": 1, "status": "chosen"}
            assert plan_source.submit_decision(export) == "module_off"
            assert bridge.sweep_once(db)["sent"] == 0
        with engine.connect() as conn:
            assert conn.execute(select(models.counsellor_intake.c.status)).scalars().all() == ["pending"]
    finally:
        ports.configure(None)
        engine.dispose()


# --- the final review's fix pass ---------------------------------------------------------------------------------

# --- PAI OS Slice 9b: the recipient lookup for PAI OS's reminder emails --------------------------------------------

def test_recipient_email_is_the_workspace_owners(student):
    assert bridge.recipient_email(student.workspace_id) == "counselor-eval@example.test"


@pytest.mark.parametrize("ref", ["", "not-a-uuid", "rehearsal-s1", "00000000-0000-4000-8000-000000000000"])
def test_recipient_email_unknown_ref_is_none(student, ref):
    assert bridge.recipient_email(ref) is None


def test_recipient_email_none_without_owner_or_when_inactive(student):
    from app.database import new_session
    from app.models import Workspace

    with new_session() as db:
        orphan = Workspace(name="Agent-made", owner_user_id=None, password_hash="synthetic-test-only")
        db.add(orphan)
        db.flush()
        orphan_id = str(orphan.id)
        db.get(Workspace, student.workspace_id).status = "archived"
        db.commit()
    assert bridge.recipient_email(orphan_id) is None
    assert bridge.recipient_email(student.workspace_id) is None


def test_recipient_email_loads_as_the_workers_lookup():
    from app.os.ports import recipients

    assert recipients.load("app.pai_os_bridge:recipient_email") is bridge.recipient_email


@pytest.mark.req("R-13")
def test_student_facts_adapter_is_off_with_the_flag_and_none_for_a_bad_reference(monkeypatch):
    """P1-T4 Task 5: the Counsellor's StudentFacts adapter answers None while CONNECT_STUDENT_FACTS is off (PAI OS then
    uses its own values) and for a reference that names no workspace."""
    monkeypatch.setattr(config, "CONNECT_STUDENT_FACTS", False)
    assert bridge.student_facts("00000000-0000-0000-0000-000000000000") is None
    monkeypatch.setattr(config, "CONNECT_STUDENT_FACTS", True)
    assert bridge.student_facts("not-a-workspace") is None


@pytest.mark.req("R-13")
def test_student_facts_adapter_builds_from_the_vault_when_on(student, monkeypatch):
    monkeypatch.setattr(config, "CONNECT_STUDENT_FACTS", True)
    got = bridge.student_facts(student.workspace_id)
    from app.os.contracts.student_facts import StudentFactsV1

    assert StudentFactsV1.model_validate(got).student_ref == str(student.workspace_id)


# ---- P1-T6 Task 4 (R-11, D-x7): the five reasons reach the endpoint unchanged; the plan then pauses ----
from app.os.contracts.escalation_v2 import EscalationV2  # noqa: E402


def escalation_v2(student, journey_id: str, reason: str, version: int | None = 1) -> EscalationV2:
    return EscalationV2(key="escalation:7", case_id=7, journey_id=journey_id, student_ref=student.workspace_id,
                        decision_version=version, reason=reason, note="A fixed note.", raised_at=T0)


@pytest.fixture
def active_decision(monkeypatch):
    """The endpoint needs an active decision when the part is on; the decision table itself is tested elsewhere."""
    from app.pai_c.roadmap.decisions import RouteDecisionService
    monkeypatch.setattr(RouteDecisionService, "active",
                        lambda self, ws: types.SimpleNamespace(decision_version=3))


@pytest.fixture
def paused(monkeypatch):
    calls = []
    monkeypatch.setattr(plan_source, "pause_for_escalation", lambda *a: calls.append(a) or True, raising=False)
    return calls


@pytest.mark.req("R-11")
@pytest.mark.parametrize("reason", ["not_eligible", "deadline_passed", "other"])
def test_bridge_sends_reason_unchanged_when_on(student, os_stub, paused, active_decision, reason):
    journey_id = journey_at(student, "CHOSEN")
    os_stub["pending"] = [escalation_v2(student, journey_id, reason, 3)]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), patch.object(config, "CONNECT_HANDOFF", True), \
            patch.object(bridge, "counsellor_module_on", lambda: True), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["sent"] == 1 and os_stub["marked"] == [("escalation:7", "sent", None)]
    with student.factory() as db:
        entry = db.get(StudentJourney, journey_id).decisions[-1]
        assert (entry["reason_type"], entry["decision_version"]) == (reason, 3)
    assert paused == [(student.workspace_id, 3, reason)]  # once, with the reason code


@pytest.mark.req("R-11")
def test_refused_escalation_does_not_pause(student, os_stub, paused):
    journey_id = journey_at(student, "CHOSEN")  # no active decision: the endpoint answers 409
    os_stub["pending"] = [escalation_v2(student, journey_id, "not_eligible")]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), patch.object(config, "CONNECT_HANDOFF", True), \
            patch.object(bridge, "counsellor_module_on", lambda: True), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["refused"] == 1 and paused == []


@pytest.mark.req("R-11")
def test_a_failed_pause_does_not_undo_the_delivery(student, os_stub, active_decision, monkeypatch):
    journey_id = journey_at(student, "CHOSEN")

    def boom(*_a):
        raise RuntimeError("os down")
    monkeypatch.setattr(plan_source, "pause_for_escalation", boom, raising=False)
    os_stub["pending"] = [escalation_v2(student, journey_id, "other", 3)]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), patch.object(config, "CONNECT_HANDOFF", True), \
            patch.object(bridge, "counsellor_module_on", lambda: True), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["sent"] == 1 and os_stub["marked"] == [("escalation:7", "sent", None)]


@pytest.mark.req("R-11")
@pytest.mark.parametrize("reason,sent_as", [("not_eligible", "route_not_possible"), ("other", "route_not_possible"),
                                            ("blocking_gap", "blocking_gap")])
def test_flags_off_no_pause_call(student, os_stub, paused, reason, sent_as):
    journey_id = journey_at(student, "CHOSEN")
    os_stub["pending"] = [escalation_v2(student, journey_id, reason)]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), student.factory() as db:
        got = bridge.sweep_once(db)
    assert got["sent"] == 1 and paused == []
    with student.factory() as db:
        assert db.get(StudentJourney, journey_id).decisions[-1]["reason_type"] == sent_as


@pytest.mark.req("R-11")
def test_a_plan_that_was_not_paused_is_logged_not_retried(student, os_stub, active_decision, monkeypatch, caplog):
    journey_id = journey_at(student, "CHOSEN")
    calls = []
    monkeypatch.setattr(plan_source, "pause_for_escalation", lambda *a: calls.append(a) or False, raising=False)
    os_stub["pending"] = [escalation_v2(student, journey_id, "other", 3)]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), patch.object(config, "CONNECT_HANDOFF", True), \
            patch.object(bridge, "counsellor_module_on", lambda: True), student.factory() as db, \
            caplog.at_level("WARNING", logger="app.pai_os_bridge"):
        got = bridge.sweep_once(db)
    assert got["sent"] == 1 and len(calls) == 1 and os_stub["marked"] == [("escalation:7", "sent", None)]
    assert any("was not paused" in r.getMessage() and "other" in r.getMessage() for r in caplog.records)
    assert student.workspace_id not in caplog.text


@pytest.mark.parametrize("module,flag,expected", [(False, False, False), (True, False, False), (False, True, False),
                                                  (True, True, True)])
def test_my_plan_enabled_needs_module_and_flag(module, flag, expected):
    """P1-T9 (R-53): the OS gate is the CONNECT_MY_PLAN part, which needs the counsellor module as well."""
    with patch.object(bridge, "counsellor_module_on", lambda: module), \
            patch.object(config, "CONNECT_MY_PLAN", flag, create=True):
        assert bridge.my_plan_enabled() is expected


def test_mount_passes_my_plan_gate():
    import inspect

    from fastapi import FastAPI

    from app import main
    from app.os.api import mount_os
    from app.os.ports import my_plan

    env = {"DATABASE_URL": "postgresql://x/y", "OS_ENABLED": "true", "OS_ADMIN_TOKEN": "t"}
    try:
        assert mount_os(FastAPI(), env=env, my_plan_enabled=lambda: True)
        assert my_plan.enabled() is True
        assert mount_os(FastAPI(), env=env)
        assert my_plan.enabled() is False  # not handed in: off
    finally:
        ports.configure(None)
    assert "my_plan_enabled=my_plan_enabled" in inspect.getsource(main)  # the host hands in its own gate
