"""Slice 7 Task 4: replan events and their detectors (spec S7-D2). Each detector records once: a second run adds
nothing. Fictional data."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.os import models
from app.os.artifacts.store import ArtifactStore
from app.os.compiler import CompileError
from app.os.kernel import Kernel, Outcome
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.replan import events
from app.os.replan.store import ProposalStore
from app.os.service import PlanService
from app.os.settings import load_settings
from app.os.workers import deadline_engine
from app.os.workers.reminders import run_reminders
from tests.os.test_golden import TEST_STUDENT

T, EV = models.tasks, models.events
P1 = "tu-chemnitz-embedded-systems"


def service(engine, today=date(2027, 2, 1), books=None) -> PlanService:
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    return PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb,
                       books or load_playbook_dir(), today=lambda: today)


def of_type(engine, plan_id, type_) -> list:
    with engine.connect() as conn:
        return conn.execute(select(EV).where(EV.c.plan_id == plan_id, EV.c.type == type_)).all()


def set_state(engine, plan_id, key, **values) -> int:
    with engine.begin() as conn:
        return conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.instance_key == key).values(**values)
                            .returning(T.c.id)).scalar_one()


@pytest.fixture
def svc(engine, clean):
    return service(engine)


def test_record_dedupes(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    with engine.begin() as conn:
        first = events.record(conn, "pai", plan_id, "escalate", {"x": 1}, "k1")
        again = events.record(conn, "pai", plan_id, "escalate", {"x": 2}, "k1")
    assert first is not None and again is None and len(of_type(engine, plan_id, "escalate")) == 1


def test_pending_until_named(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    with engine.begin() as conn:
        eid = events.record(conn, "pai", plan_id, "escalate", {}, "k1")
        conn.execute(EV.insert().values(tenant_id="pai", plan_id=plan_id, type="plan_created", payload={}))
    assert [e.id for e in events.pending(engine, "pai")] == [eid]  # only the replan types
    ProposalStore(engine, "pai").create(plan_id, [eid], "rules", [], [], big=False, expires_at=None, status="applied")
    assert events.pending(engine, "pai") == []


def test_task_failed_recorded_once(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    task_id = set_state(engine, plan_id, "applications_submitted", state="running", attempt=1)
    svc.kernel.apply_result(task_id, 1, Outcome("failed", reason="budget_exceeded"))
    svc.kernel.apply_result(task_id, 1, Outcome("failed", reason="budget_exceeded"))  # a repeat: ignored
    got = of_type(engine, plan_id, "task_failed")
    assert len(got) == 1 and got[0].task_id == task_id and got[0].payload["reason"] == "budget_exceeded"


def test_admission_rejected_recorded(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    task_id = set_state(engine, plan_id, f"admission_result@{P1}", state="waiting_student")
    assert svc.kernel.complete_student_task(task_id, TEST_STUDENT.student_ref, {"choice": "rejected"})
    got = of_type(engine, plan_id, "admission_rejected")
    assert len(got) == 1 and got[0].payload["programme_ref"] == P1
    admitted = set_state(engine, plan_id, "admission_result@ovgu-eeit", state="waiting_student")
    svc.kernel.complete_student_task(admitted, TEST_STUDENT.student_ref, {"choice": "admitted"})
    assert len(of_type(engine, plan_id, "admission_rejected")) == 1  # an admission is not a rejection


def test_deadline_at_risk_recorded_once(engine, clean):
    late = service(engine, today=date(2027, 7, 1))  # past most deadlines: the critical path has negative slack
    plan_id = late.start_plan(TEST_STUDENT).plan_id
    deadline_engine.run(late, engine)
    first = len(of_type(engine, plan_id, "deadline_at_risk"))
    deadline_engine.run(late, engine)
    assert first >= 1 and len(of_type(engine, plan_id, "deadline_at_risk")) == first


def test_route_invalid_recorded(svc, engine, monkeypatch):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id

    def broken(*a, **k):
        raise CompileError("a cycle in the plan")

    monkeypatch.setattr(svc, "compile", broken)
    deadline_engine.run(svc, engine)
    deadline_engine.run(svc, engine)
    got = of_type(engine, plan_id, "route_invalid")
    assert len(got) == 1 and "cycle" in got[0].payload["error"]


def test_document_missing_recorded_once(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    due = datetime(2027, 2, 10, 22, 59, tzinfo=timezone.utc)
    set_state(engine, plan_id, "hec_attestation", state="waiting_student", due_at=due)
    outbox, later = Outbox(engine, "pai"), due + timedelta(days=2)
    run_reminders(engine, outbox, later, "pai")
    run_reminders(engine, outbox, later + timedelta(hours=1), "pai")
    got = of_type(engine, plan_id, "document_missing")
    assert len(got) == 1 and got[0].payload["instance_key"] == "hec_attestation"


def test_playbook_newer_recorded_once(engine, clean):
    books = load_playbook_dir()
    (key, version), book = next(((k, v), b) for (k, v), b in books.items() if k == "germany_master")
    svc = service(engine)
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    newer = {**books, (key, version + 1): book.model_copy(update={"version": version + 1})}
    svc2 = service(engine, books=newer)
    assert svc2.check_newer(plan_id) is True
    assert svc2.check_newer(plan_id) is False
    got = of_type(engine, plan_id, "playbook_newer")
    assert len(got) == 1 and got[0].payload["version"] == version + 1
    assert svc.check_newer(plan_id) is False  # no newer version: nothing


def test_approved_changed_recorded_once(svc, engine):
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    arts = ArtifactStore(engine, "pai")
    art = arts.get_or_create(TEST_STUDENT.student_ref, "visa", None)
    v1 = arts.add_version(art.id, '{"fictional": 1}', "system")
    arts.approve(art.id, v1.number)
    set_state(engine, plan_id, "review_visa_file", state="done", result={"artifacts": {"visa": v1.sha256}})
    assert events.detect_approved_changed(engine, "pai", plan_id) == 0  # still the approved version
    arts.add_version(art.id, '{"fictional": 2}', "system")  # e.g. another programme chosen: approval dropped
    assert events.detect_approved_changed(engine, "pai", plan_id) == 1
    assert events.detect_approved_changed(engine, "pai", plan_id) == 0
    got = of_type(engine, plan_id, "approved_changed")
    assert got[0].payload["template_key"] == "review_visa_file"


def test_old_events_are_not_pending(svc, engine):
    """Final review I11: events logged before Slice 7 (no dedupe key) never flood the replan job at deploy."""
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    with engine.begin() as conn:
        conn.execute(EV.insert().values(tenant_id="pai", plan_id=plan_id, type="escalate", payload={"task_id": 1}))
    assert events.pending(engine, "pai") == []


def test_escalation_names_its_step(svc, engine):
    """Final review I11: the reminders' escalation carries the step's key (the only field the Supervisor may see)."""
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    due = datetime(2027, 2, 10, 22, 59, tzinfo=timezone.utc)
    set_state(engine, plan_id, "travel_insurance", state="waiting_student", due_at=due)
    outbox = Outbox(engine, "pai")
    run_reminders(engine, outbox, due + timedelta(minutes=30), "pai")
    run_reminders(engine, outbox, due + timedelta(minutes=50), "pai")  # the same day's slot: no second escalation
    got = [e for e in events.pending(engine, "pai") if e.type == "escalate"]
    assert len(got) == 1 and got[0].payload["instance_key"] == "travel_insurance"
