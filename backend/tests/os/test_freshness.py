"""Slice 2 Task 7: the freshness sweeper (spec §4.7, R2-P2) and intake-year matching (handoff M17)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.os import models
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Outcome
from app.os.knowledge import Fact
from app.os.workers import confirm_fact
from app.os.workers import freshness
from app.os.workers.jobs import JOB_FACTORIES
from tests.os.kernel_helpers import contract
from tests.os.test_workers import service, task

URL, QUOTE = "https://uni.example/apply", "Deadline: 15 July 2027"
NOW = datetime(2027, 3, 1, 9, tzinfo=timezone.utc)


def put(kb, field="deadline_close", value=None, status="confirmed", checked=NOW, year=2027, ref="p1") -> int:
    value = value if value is not None else {"date": "2027-07-15", "tz": "Europe/Berlin"}
    quote, url = (QUOTE, URL) if status == "confirmed" else ("", "")
    return kb.upsert("programme", ref, field, Fact(value, quote, url, checked, year, status))


def status_of(engine, fact_id) -> str:
    with engine.connect() as conn:
        return conn.execute(select(models.knowledge_facts.c.status).where(models.knowledge_facts.c.id == fact_id)).scalar()


def events(engine, kind="fact_changed") -> list:
    with engine.connect() as conn:
        return conn.execute(select(models.events.c.payload).where(models.events.c.type == kind)).scalars().all()


def to_review(kernel, row) -> None:
    """What the runner does: the confirm task runs and waits for review."""
    kernel.mark_running(row.id, row.attempt)
    kernel.apply_result(row.id, row.attempt, Outcome("needs_review", {"waiting_for": "research"}))


def test_old_confirmed_fact_goes_stale(engine, clean):
    svc, kb, _ = service(engine)
    old = put(kb, field="application_route", value="direct", checked=NOW - timedelta(days=31))
    fresh = put(kb, field="semester_contribution_eur", value=300.0, checked=NOW - timedelta(days=10))
    assert freshness.run(svc, engine, NOW, ttl_days=30) == 1
    assert status_of(engine, old) == "stale" and status_of(engine, fresh) == "confirmed"
    [e] = events(engine)
    assert (e["field"], e["reason"], e["old"]["status"], e["new"]["status"]) == ("application_route", "ttl", "confirmed", "stale")
    assert freshness.run(svc, engine, NOW, ttl_days=30) == 0  # idempotent


def test_deadline_fact_stale_at_30_and_7_days(engine, clean):
    svc, kb, _ = service(engine)
    # Deadline 15 July 2027, Berlin. The 30-day mark is 15 June (Berlin), the 7-day mark 8 July.
    fid = put(kb, checked=datetime(2027, 6, 10, tzinfo=timezone.utc))
    assert freshness.run(svc, engine, datetime(2027, 6, 14, 21, tzinfo=timezone.utc)) == 0  # 14 Jun 23:00 Berlin
    assert freshness.run(svc, engine, datetime(2027, 6, 14, 22, 30, tzinfo=timezone.utc)) == 1  # 15 Jun 00:30 Berlin
    assert status_of(engine, fid) == "stale" and events(engine)[-1]["reason"] == "recheck_30d"
    # research re-confirms it on 15 June; nothing until the 7-day mark
    put(kb, checked=datetime(2027, 6, 15, 12, tzinfo=timezone.utc))
    assert freshness.run(svc, engine, datetime(2027, 7, 6, 12, tzinfo=timezone.utc)) == 0
    assert freshness.run(svc, engine, datetime(2027, 7, 8, 12, tzinfo=timezone.utc)) == 1
    assert events(engine)[-1]["reason"] == "recheck_7d"


def test_stale_triggers_confirm_task_and_research(engine, clean):
    svc, kb, kernel = service(engine)
    fid = put(kb, status="unconfirmed", value={"date": "2027-07-15"})
    plan_id = svc.start_plan(contract()).plan_id
    to_review(kernel, task(engine, plan_id, "confirm_fact@p1:deadline_close"))
    confirm_fact(svc, kb, kernel, fid, value={"date": "2027-07-15"}, quote=QUOTE, url=URL, status="confirmed")
    assert task(engine, plan_id, "confirm_fact@p1:deadline_close").state == "done"
    assert not task(engine, plan_id, "apply@p1").provisional
    later = datetime.now(timezone.utc) + timedelta(days=40)
    assert freshness.run(svc, engine, later, ttl_days=30) == 1
    # the done check is history under a new key; a fresh confirm task is ready, so research runs again
    with engine.connect() as conn:
        keys = {r.instance_key: r.state for r in conn.execute(select(models.tasks.c.instance_key, models.tasks.c.state)
                .where(models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key.like("confirm_fact@p1:%")))}
        sent = conn.execute(select(models.enqueue_requests.c.task_id).where(models.enqueue_requests.c.sent.is_(False))).all()
    fresh = task(engine, plan_id, "confirm_fact@p1:deadline_close")
    assert fresh.state == "ready" and fresh.id in {r.task_id for r in sent}
    assert [s for k, s in keys.items() if k != "confirm_fact@p1:deadline_close"] == ["done"]
    assert task(engine, plan_id, "apply@p1").provisional


def test_confirm_matches_intake_year(engine, clean):
    svc, kb, kernel = service(engine)
    f27 = put(kb, status="unconfirmed", value={"date": "2027-07-15"}, year=2027)
    put(kb, status="unconfirmed", value={"date": "2028-07-15"}, year=2028)
    p27 = svc.start_plan(contract()).plan_id
    data = contract(external_ref="ext-2", student_ref="stu-2").model_dump(mode="json")
    p28 = svc.start_plan(RouteContract.model_validate({**data, "target_intake": {"term": "winter", "year": 2028}})).plan_id
    for p in (p27, p28):
        to_review(kernel, task(engine, p, "confirm_fact@p1:deadline_close"))
    revised = confirm_fact(svc, kb, kernel, f27, value={"date": "2027-07-15"}, quote=QUOTE, url=URL, status="confirmed")
    assert revised == [p27]
    assert task(engine, p27, "confirm_fact@p1:deadline_close").state == "done"
    assert task(engine, p28, "confirm_fact@p1:deadline_close").state == "waiting_review"  # the 2028 fact is still open


def test_freshness_schedule_registered():
    jobs = {name: cron for name, cron, _ in JOB_FACTORIES}
    assert jobs["freshness"] == "0 3 * * *"  # daily, 03:00 UTC
