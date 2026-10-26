"""Slice 8 Task 6: PlanSummary v1 (spec §2.4, S8-D13): built on every read, no private details. Fictional data;
plan rows are the tests' own writes (the kernel writes them in the app)."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import insert

from app.os import models, ports
from app.os.ports import plan_query
from app.os.contracts.plan_summary import PlanSummaryV1
from app.os.summary import build_summary
from tests.os.test_golden import TEST_STUDENT

NOW = datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc)
STUDENT = "ws-1"
CONTRACT = {**TEST_STUDENT.model_dump(mode="json"), "student_ref": STUDENT}


def plan(engine, status="active", paused=False, source="counsellor", ref="j-1:DE:master") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source=source, external_ref=ref, student_ref=STUDENT, contract=CONTRACT,
            contract_sha256="0" * 64, status=status, changes_paused=paused).returning(models.plans.c.id)).scalar_one()


def task(engine, plan_id, key, state="pending", kind="work", due=None, blocked=None, programme=None, title=None):
    with engine.begin() as conn:
        conn.execute(insert(models.tasks).values(
            tenant_id="pai", plan_id=plan_id, instance_key=key, template_key=key.split("@")[0], task_type="x",
            kind=kind, inbox_kind="act" if kind == "student" else None, programme_ref=programme,
            title=title or f"Step {key}", state=state, blocked_reason=blocked, due_at=due, due_tz="Europe/Berlin",
            playbook_version=1))


def summary(engine):
    return build_summary(engine, "pai", STUDENT, NOW)


def test_state_on_track(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "done")
    task(engine, p, "b", "running")
    s = summary(engine)
    assert (s.state, s.plan_id, s.student_ref) == ("on_track", p, STUDENT)
    assert (s.route.destination_country, s.route.level, s.route.target_intake.year) == ("DE", "master", 2027)
    assert s.waiting_on_student == [] and s.blocked == [] and s.support_case_open is False


def test_state_needs_student_open_item(engine, clean):
    p = plan(engine)
    task(engine, p, "upload_passport", "waiting_student", kind="student", title="Upload your passport")
    s = summary(engine)
    assert s.state == "needs_student"
    assert [(w.title, w.template_key, w.due_at) for w in s.waiting_on_student] == [
        ("Upload your passport", "upload_passport", None)]


def test_state_needs_student_pending_proposal(engine, clean):
    p = plan(engine)
    task(engine, p, "b", "running")
    with engine.begin() as conn:
        conn.execute(insert(models.proposals).values(tenant_id="pai", plan_id=p, source="rules", status="pending"))
    assert summary(engine).state == "needs_student"


@pytest.mark.parametrize("status,paused", [("paused", False), ("active", True)])
def test_state_paused_changes_paused(engine, clean, status, paused):
    p = plan(engine, status=status, paused=paused)
    task(engine, p, "x", "waiting_student", kind="student")  # paused wins over an open item
    assert summary(engine).state == "paused"


def test_state_finished(engine, clean):
    p = plan(engine, status="done")
    task(engine, p, "a", "done")
    s = summary(engine)
    assert (s.state, s.plan_id) == ("finished", p)


def test_no_plan_is_none(engine, clean):
    assert summary(engine) is None


def test_next_deadlines_three_with_tz(engine, clean):
    p = plan(engine)
    for n, days in enumerate((9, -2, 3, 5, 1)):
        task(engine, p, f"d{n}@prog-{n}", due=NOW + timedelta(days=days), programme=f"prog-{n}")
    task(engine, p, "gone", "cancelled", due=NOW + timedelta(hours=1))  # finished steps never count
    s = summary(engine)
    assert [d.template_key for d in s.next_deadlines] == ["d4", "d2", "d3"]  # future only, soonest first, 3 at most
    first = s.next_deadlines[0]
    assert (first.programme_ref, first.due_tz) == ("prog-4", "Europe/Berlin")
    assert first.due_at == NOW + timedelta(days=1) and first.due_at.utcoffset() == timedelta(hours=1)  # its own zone


def test_blocked_reason_codes(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "blocked", blocked="missing_input")
    task(engine, p, "b", "blocked", blocked="Waiting for the passport scan of Ms Example")  # free text: never shown
    s = summary(engine)
    assert [(b.template_key, b.reason) for b in s.blocked] == [("a", "missing_input"), ("b", "blocked")]


def test_no_free_text(engine, clean):
    p = plan(engine)
    task(engine, p, "b", "blocked", blocked="Passport number AB1234567 does not match")
    with engine.begin() as conn:
        conn.execute(insert(models.support_cases).values(
            tenant_id="pai", plan_id=p, student_ref=STUDENT, reason="Admin note: family cannot pay the fee"))
        conn.execute(insert(models.tasks).values(  # a done reading step holding a document value
            tenant_id="pai", plan_id=p, instance_key="read_passport", template_key="read_passport", task_type="x",
            kind="work", title="Read your passport", state="done", due_tz="Europe/Berlin", playbook_version=1,
            result={"passport.number": "AB1234567"}))
    text = json.dumps(summary(engine).model_dump(mode="json", by_alias=True))
    assert "AB1234567" not in text and "family" not in text
    assert summary(engine).support_case_open is True


def test_summary_skips_closed_plans(engine, clean):
    old = plan(engine, ref="j-1:DE:master")
    new = plan(engine, ref="j-1:IE:master")
    with engine.begin() as conn:
        conn.execute(models.plans.update().where(models.plans.c.id == old).values(status="closed"))
    assert summary(engine).plan_id == new  # review focus 5
    with engine.begin() as conn:
        conn.execute(models.plans.update().where(models.plans.c.id == new).values(status="closed"))
    assert summary(engine) is None  # only closed plans: nothing to show


def test_summary_validates(engine, clean, os_db):
    from app.os.api.services import make_services
    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.settings import load_settings

    svc = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine, today=lambda: date(2027, 2, 1))
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    svc.plans.start_plan(TEST_STUDENT)  # a real compiled plan
    ports.configure(svc)
    try:
        s = plan_query.plan_summary(TEST_STUDENT.student_ref)
    finally:
        ports.configure(None)
    assert PlanSummaryV1.model_validate(s.model_dump(mode="json", by_alias=True)) == s
    assert s.schema_ == "pai.plan_summary.v1" and len(s.next_deadlines) <= 3
