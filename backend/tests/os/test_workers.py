from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, insert, select

from app.os import models
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.outbox import Outbox
from app.os.playbooks import Playbook
from app.os.service import PlanService
from app.os.settings import load_settings
from app.os.workers import confirm_fact, deadline_engine, run_reminders
from tests.os.kernel_helpers import contract

CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
TODAY = date(2027, 3, 1)


def book() -> Playbook:
    return Playbook.model_validate({
        "key": "test_route", "version": 1, "route": {"origin": "PK", "destination": "IE", "level": "master"},
        "default_timezone": "Europe/Dublin",
        "tasks": [
            {"template_key": "m", "task_type": "system.milestone", "title": "Prepare", "kind": "work",
             "fan_out": "programme", "anchor": {"fact": "deadline_close"}, "lead_time": {"days": 30}},
            {"template_key": "apply", "task_type": "student.act", "title": "Apply", "kind": "student",
             "inbox_kind": "act", "fan_out": "programme", "anchor": {"fact": "deadline_close"}, "duration_days": 3,
             "depends_on": [{"key": "m", "hard": False}]},
            {"template_key": "visa", "task_type": "student.act", "title": "Visa", "kind": "student",
             "inbox_kind": "act", "depends_on": [{"key": "apply"}]},
        ],
    })


def service(engine) -> tuple[PlanService, SqlKnowledge, Kernel]:
    settings = load_settings({"DATABASE_URL": "x"})
    kernel = Kernel(engine, "pai")
    kb = SqlKnowledge(engine, "pai")
    svc = PlanService(engine, settings, kernel, kb, {("test_route", 1): book()}, today=lambda: TODAY)
    return svc, kb, kernel


def seed_deadline(kb, day="2027-07-15", status="confirmed") -> int:
    quote, url = ("Deadline", "https://uni.example/apply") if status == "confirmed" else ("", "")
    return kb.upsert("programme", "p1", "deadline_close", Fact({"date": day}, quote, url, CHECKED, 2027, status))


def task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).one()


def revisions(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.plan_revisions)).scalar_one()


def test_start_plan_uses_seeded_facts(engine, clean):
    svc, kb, _ = service(engine)
    seed_deadline(kb)
    ref = svc.start_plan(contract())
    assert task(engine, ref.plan_id, "apply@p1").due_at.date() == date(2027, 7, 15)


def test_deadline_engine_noop_when_unchanged(engine, clean):
    svc, kb, _ = service(engine)
    seed_deadline(kb)
    svc.start_plan(contract())
    assert deadline_engine.run(svc, engine) == 0
    assert revisions(engine) == 1


def test_fact_change_keeps_started_tasks(engine, clean):
    svc, kb, kernel = service(engine)
    seed_deadline(kb)
    ref = svc.start_plan(contract())
    m = task(engine, ref.plan_id, "m@p1")
    assert kernel.mark_running(m.id, 1)
    old_m_due = m.due_at
    seed_deadline(kb, day="2027-06-30")
    assert deadline_engine.run(svc, engine) == 1
    assert task(engine, ref.plan_id, "m@p1").due_at == old_m_due  # started: untouched
    assert task(engine, ref.plan_id, "apply@p1").due_at.date() == date(2027, 6, 30)
    with engine.connect() as conn:
        diff = conn.execute(select(models.plan_revisions.c.diff).where(models.plan_revisions.c.number == 2)).scalar_one()
    assert diff["skipped_started"] == ["m@p1"] and "apply@p1" in diff["changed"]


def test_confirm_fact_completes_task_and_firms_date(engine, clean):
    svc, kb, kernel = service(engine)
    fid = seed_deadline(kb, status="unconfirmed")
    ref = svc.start_plan(contract())
    assert task(engine, ref.plan_id, "apply@p1").provisional
    confirm = task(engine, ref.plan_id, "confirm_fact@p1:deadline_close")
    kernel.mark_running(confirm.id, confirm.attempt)
    from app.os.kernel import Outcome
    kernel.apply_result(confirm.id, confirm.attempt, Outcome("needs_review"))
    revised = confirm_fact(svc, kb, kernel, fid, value={"date": "2027-07-15"}, quote="Deadline 15 July",
                           url="https://uni.example/apply", status="confirmed")
    assert revised == [ref.plan_id]
    assert task(engine, ref.plan_id, "confirm_fact@p1:deadline_close").state == "done"
    assert not task(engine, ref.plan_id, "apply@p1").provisional


def test_module_disabled_applies_fallback(engine, clean):
    svc, kb, _ = service(engine)
    seed_deadline(kb)
    ref = svc.start_plan(contract())
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="milestone", tenant_id="pai", enabled=False))
    assert svc.recompile(ref.plan_id, "module_disabled") == 2
    assert task(engine, ref.plan_id, "m@p1#c2").state == "cancelled"  # renamed so the key can return


def test_reminders_rerun_same_slot_no_new_rows(engine, clean):
    svc, kb, kernel = service(engine)
    seed_deadline(kb)
    ref = svc.start_plan(contract())
    m = task(engine, ref.plan_id, "m@p1")
    kernel.mark_running(m.id, 1)
    from app.os.kernel import Outcome
    kernel.apply_result(m.id, 1, Outcome("done"))  # apply@p1 is now waiting_student (soft dep anyway)
    box = Outbox(engine, "pai")
    now = datetime(2027, 3, 2, 8, tzinfo=timezone.utc)
    assert run_reminders(engine, box, now, "pai") == 1
    assert run_reminders(engine, box, now + timedelta(minutes=30), "pai") == 0
    with engine.connect() as conn:
        row = conn.execute(select(models.outbox)).one()
    assert row.recipient == "stu-1" and row.idempotency_key.startswith(f"reminder:{task(engine, ref.plan_id, 'apply@p1').id}:")


def test_overdue_reminder_escalates(engine, clean):
    svc, kb, _ = service(engine)
    seed_deadline(kb, day="2027-03-05")
    svc.start_plan(contract())
    box = Outbox(engine, "pai")
    run_reminders(engine, box, datetime(2027, 3, 8, 8, tzinfo=timezone.utc), "pai")
    with engine.connect() as conn:
        types = set(conn.execute(select(models.events.c.type)).scalars())
        keys = conn.execute(select(models.outbox.c.idempotency_key)).scalars().all()
    assert "escalate" in types and any(":esc:" in k for k in keys)
