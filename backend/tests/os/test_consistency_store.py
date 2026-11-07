"""P1-T10 A1: the consistency case store (R-05). Fictional data."""

from datetime import date

import pytest
from sqlalchemy import insert, select

from app.os import clock, models
from app.os.consistency.store import ConsistencyStore
from app.os.replan.store import SupportStore

pytestmark = pytest.mark.req("R-05")


@pytest.fixture
def store(engine, clean):
    return ConsistencyStore(engine, "pai")


def _plan(engine, student="stu-1") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref=f"j-{student}:XX:master", student_ref=student,
            contract={}, contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def test_open_or_touch_keeps_one_open_case_per_student_and_rule(store):
    first, created = store.open_or_touch("stu-1", 2, None, ["contract_hash"])
    again, created_again = store.open_or_touch("stu-1", 2, None, ["contract_hash", "export_hash"])
    assert (created, created_again, again) == (True, False, first)
    case = store.get(first)
    assert case.codes == ["contract_hash", "export_hash"]
    assert case.last_seen_at >= case.first_seen_at
    assert len(store.list("open")) == 1
    store.open_or_touch("stu-1", 3, None, ["plan_not_stopped"])
    store.open_or_touch("stu-2", 2, None, ["contract_hash"])
    assert len(store.list("open")) == 3


def test_a_resolved_case_lets_a_new_mismatch_open_a_new_row(store):
    first, _ = store.open_or_touch("stu-1", 1, None, ["no_plan"])
    assert store.resolve(first, "checked by a person") is True
    assert store.resolve(first, "again") is False  # only an open case resolves
    second, created = store.open_or_touch("stu-1", 1, None, ["no_plan"])
    assert created and second != first
    assert store.get(first).status == "resolved" and store.get(first).resolution == "checked by a person"
    assert [c.id for c in store.list("open")] == [second]


def test_resolve_never_touches_a_plan_or_its_pause(engine, store):
    plan = _plan(engine)
    case, _ = store.open_or_touch("stu-1", 2, plan, ["contract_hash"])
    with engine.begin() as conn:
        conn.execute(models.plans.update().where(models.plans.c.id == plan).values(
            status="paused", changes_paused=True))
        before = conn.execute(select(models.plans).where(models.plans.c.id == plan)).one()
        n_events = conn.execute(select(models.events.c.id)).all()
    store.resolve(case, "done")
    with engine.connect() as conn:
        assert conn.execute(select(models.plans).where(models.plans.c.id == plan)).one() == before
        assert conn.execute(select(models.events.c.id)).all() == n_events
    assert before.status == "paused" and before.changes_paused is True


def test_one_run_per_date_across_two_claims(store):
    day = date(2027, 3, 1)
    run = store.claim_run(day, "nightly")
    assert run is not None
    assert store.claim_run(day, "nightly") is None  # the second replica loses
    assert store.claim_run(date(2027, 3, 2), "nightly") is not None
    store.finish_run(run, {"1": 2})
    last = store.last_run()
    assert last["run_date"] == date(2027, 3, 2) and last["finished_at"] is None


def test_cases_never_reach_the_escalation_channel(engine, store):
    from app.os import ports
    from app.os.ports import escalation
    plan = _plan(engine)
    store.open_or_touch("stu-1", 2, plan, ["contract_hash"])
    ports.configure(_svc(engine))
    try:
        assert escalation.pending_counsellor_escalations() == []
    finally:
        ports.configure(None)
    with engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.id)).all() == []
        assert conn.execute(select(models.events.c.id)).all() == []


def _svc(engine):
    from app.os.api.services import make_services
    from app.os.settings import load_settings
    return make_services(load_settings({"OS_DATABASE_URL": str(engine.url.render_as_string(hide_password=False))}),
                         engine=engine, playbooks={}, today=lambda: date(2027, 1, 20))
