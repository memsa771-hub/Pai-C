"""P1-T6 Task 6 (R-11, carried from the Task 4 review): a plan paused for a missing consent and then for an escalation
shows the student one "paused" notice, not two. The escalation still replaces the pause reason (a `plan_paused` event
of its own); only its notice is quiet. Fictional student."""

import pytest
from sqlalchemy import insert, select

from app.os import models, ports
from app.os.adapters.counsellor.store import IntakeStore
from app.os.ports import os_events, plan_source
from tests.os.test_counsellor_intake_v2 import chosen, run, svc, v2  # noqa: F401 - fixture by name

pytestmark = pytest.mark.req("R-11")


@pytest.fixture
def world(svc, engine):  # noqa: F811
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(svc)
    try:
        yield svc
    finally:
        ports.configure(None)


def paused_events(svc_, plan_id):
    with svc_.engine.connect() as conn:
        return conn.execute(select(models.events.c.payload).where(
            models.events.c.plan_id == plan_id, models.events.c.type == "plan_paused").order_by(models.events.c.id)
        ).scalars().all()


def test_escalation_after_a_consent_pause_makes_one_paused_notice(world):
    result = run(world, chosen(1))
    store = IntakeStore(world.engine, "pai")
    store.finish(store.get("d-v1").id, result.status, result.reason, result.plan_id)
    assert world.kernel.pause_plan(result.plan_id, "consent_missing") is True
    assert plan_source.pause_for_escalation("ws-sample-1", 1, "other") is True
    assert [p["reason"] for p in paused_events(world, result.plan_id)] == ["consent_missing", "other"]
    kinds = [e.kind for e in os_events.pending_events()]
    assert kinds.count("plan_paused") == 1, kinds  # one notice for one pause
    # and a plan paused by an escalation alone still tells the student once
    other = run(world, v2(student_ref="ws-two", decision_id="d-two", journey_id="j-two"))
    store.finish(store.get("d-two").id, other.status, other.reason, other.plan_id)
    assert plan_source.pause_for_escalation("ws-two", 1, "other") is True
    assert [e.kind for e in os_events.pending_events()].count("plan_paused") == 2
