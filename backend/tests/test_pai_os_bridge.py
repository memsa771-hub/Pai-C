"""Slice 8 Task 8: the glue between the Counsellor and PAI OS (PAI OS Slice 8 spec §2.7). Host code. The OS ports are
stubbed here (the legacy suite has no OS database); the Counsellor's escalation code is the real one. Fictional."""

import os
import sys
import types
from datetime import datetime, timedelta, timezone
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
def export_fn(monkeypatch):
    """The Counsellor's export function, as it will exist (`app.pai_c.os_export.decision_record_v1`)."""
    calls = []
    module = types.ModuleType("app.pai_c.os_export")

    def decision_record_v1(db, workspace_id):
        calls.append(workspace_id)
        return {"schema": "pai.decision_record.v1", "decision_id": f"d-{len(calls)}", "journey_id": "j-1",
                "student_ref": workspace_id, "chosen_at": T0.isoformat()}

    module.decision_record_v1 = decision_record_v1
    monkeypatch.setitem(sys.modules, "app.pai_c.os_export", module)
    return calls


@pytest.fixture
def os_stub(monkeypatch):
    """The OS ports, recorded: mounted; the module on for the sweep, while a submit answers `module_off`."""
    got = {"submitted": [], "mark": None, "marked": [], "pending": []}
    monkeypatch.setattr(plan_source, "counsellor_enabled", lambda: True, raising=False)
    monkeypatch.setattr(plan_source, "submit_counsellor_decision",
                        lambda export: got["submitted"].append(export) or "module_off")
    monkeypatch.setattr(plan_source, "sweep_mark", lambda: got["mark"])
    monkeypatch.setattr(plan_source, "set_sweep_mark", lambda mark: got.__setitem__("mark", mark))
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


def record(db, workspace_id: str, n: int, chosen_at: datetime) -> str:
    db.execute(text("PRAGMA foreign_keys=OFF"))  # the roadmap and journey rows are not needed for the sweep
    # Merge pai-c + pai-os: pai-c's decision record is RouteDecision (migration 119 dropped the old model). One
    # active row per workspace, so each fake row is already withdrawn (the sweep reads every row by chosen_at).
    # Ids are UUIDs with letters: SQLite would store all-digit hex as a number.
    row = RouteDecision(id=f"decd{n:04d}-aaaa-4aaa-8aaa-aaaaaaaaaaaa", workspace_id=workspace_id,
                        field_key="f-1", title="Route", verdict={}, route={}, steps=[], steps_done=[], chosen_at=chosen_at, withdrawn_at=chosen_at)
    db.add(row)
    db.commit()
    return row.id


def test_no_export_yet_is_none(student):
    sys.modules.pop("app.pai_c.os_export", None)
    with student.factory() as db:
        assert bridge.current_export(db, student.workspace_id) is None  # "not ready for PAI OS"


def test_decision_changed_submits_export(student, export_fn, os_stub):
    with student.factory() as db:
        assert bridge.decision_changed(student.workspace_id, db) == "module_off"
    assert export_fn == [student.workspace_id]
    assert [e["student_ref"] for e in os_stub["submitted"]] == [student.workspace_id]


def test_decision_changed_without_export_submits_nothing(student, os_stub):
    sys.modules.pop("app.pai_c.os_export", None)
    with student.factory() as db:
        assert bridge.decision_changed(student.workspace_id, db) is None
    assert os_stub["submitted"] == []


def test_sweep_submits_since_mark_and_moves_it(student, export_fn, os_stub):
    with student.factory() as db:
        first = record(db, student.workspace_id, 1, T0)
        os_stub["mark"] = {"chosen_at": T0.isoformat(), "decision_id": first}
        second = record(db, student.workspace_id, 2, T0 + timedelta(hours=1))
        record(db, student.workspace_id, 3, T0 + timedelta(minutes=30))  # also after the mark: one export per student
        got = bridge.sweep_once(db)
        assert got["submitted"] == 1 and len(os_stub["submitted"]) == 1
        assert os_stub["mark"] == {"chosen_at": (T0 + timedelta(hours=1)).isoformat(), "decision_id": second}
        assert bridge.sweep_once(db)["submitted"] == 0  # nothing new since the mark


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


def test_os_not_mounted_noop(student, export_fn):
    ports.configure(None)
    with student.factory() as db:
        record(db, student.workspace_id, 1, T0)
        assert bridge.decision_changed(student.workspace_id, db) is None
        assert bridge.sweep_once(db) == {"mounted": False}


@pytest.mark.skipif(not os.environ.get("OS_TEST_DATABASE_URL"), reason="needs the PAI OS test database")
def test_module_off_by_default_end_to_end(student, export_fn):
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
            assert bridge.decision_changed(student.workspace_id, db) == "module_off"
            assert bridge.sweep_once(db)["sent"] == 0
        with engine.connect() as conn:
            assert conn.execute(select(models.counsellor_intake.c.status)).scalars().all() == ["pending"]
    finally:
        ports.configure(None)
        engine.dispose()


# --- the final review's fix pass ---------------------------------------------------------------------------------

def test_sweep_submits_nothing_while_module_off(student, export_fn, os_stub, monkeypatch):
    """S8-D2: while the module is off the sweep submits nothing and keeps its mark, so switching on replays from
    there; escalations (none can be raised while off) are still delivered."""
    monkeypatch.setattr(plan_source, "counsellor_enabled", lambda: False)
    os_stub["pending"] = [escalation(student, journey_at(student, "CHOSEN"))]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), student.factory() as db:
        record(db, student.workspace_id, 1, T0)
        got = bridge.sweep_once(db)
    assert got["submitted"] == 0 and os_stub["submitted"] == [] and os_stub["mark"] is None
    assert got["sent"] == 1


def test_sweep_survives_a_bad_export(student, os_stub, monkeypatch):
    """One export that cannot be submitted never stops the sweep: the mark moves and escalations go out."""
    module = types.ModuleType("app.pai_c.os_export")
    module.decision_record_v1 = lambda db, ws: {"schema": "pai.decision_record.v1"}  # no decision_id
    monkeypatch.setitem(sys.modules, "app.pai_c.os_export", module)
    monkeypatch.setattr(plan_source, "submit_counsellor_decision",
                        lambda export: (_ for _ in ()).throw(ValueError("export lacks decision_id")))
    os_stub["pending"] = [escalation(student, journey_at(student, "CHOSEN"))]
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", TOKEN), student.factory() as db:
        last = record(db, student.workspace_id, 1, T0)
        got = bridge.sweep_once(db)
    assert (got["submitted"], got["failed"], got["sent"]) == (0, 1, 1)
    assert os_stub["mark"]["decision_id"] == last


def test_decision_changed_with_a_bad_export_is_none(student, os_stub, monkeypatch):
    module = types.ModuleType("app.pai_c.os_export")
    module.decision_record_v1 = lambda db, ws: {"schema": "pai.decision_record.v1"}
    monkeypatch.setitem(sys.modules, "app.pai_c.os_export", module)
    monkeypatch.setattr(plan_source, "submit_counsellor_decision",
                        lambda export: (_ for _ in ()).throw(ValueError("export lacks decision_id")))
    with student.factory() as db:
        assert bridge.decision_changed(student.workspace_id, db) is None  # logged; never raised at the Counsellor


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
