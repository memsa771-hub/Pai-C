"""P1-T5 Task 4: OS plan events for the Counsellor (R-45, R-04). The kernel, the deadline detector and the proposal store
write one `os_event.v1` row into the `counsellor` outbox channel, in the same transaction, only while the module is
on. Fictional data."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, insert, select, update

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api.services import make_services
from app.os.contracts.os_event import OsEventV1
from app.os.kernel import Outcome
from app.os.outbox import Outbox
from app.os.ports import os_events
from app.os.ports.escalation import mark_counsellor_delivery, pending_counsellor_escalations
from app.os.replan import events as replan_events
from app.os.replan.store import ProposalStore
from app.os.settings import load_settings
from tests.os.kernel_helpers import contract, draft, kernel, playbook

O = models.outbox
pytestmark = [pytest.mark.req("R-45"), pytest.mark.req("R-04")]


@pytest.fixture
def on(engine, clean):
    manifest.set_enabled(engine, "pai", True)


def counsellor_contract(**kw):
    return contract(**kw).model_copy(update={"source": "counsellor"})


def rows(engine, kind: str | None = None) -> list[dict]:
    with engine.connect() as conn:
        found = conn.execute(select(O).where(O.c.channel == "counsellor", O.c.template == "os_event")
                             .order_by(O.c.id)).all()
    return [{"key": r.idempotency_key, "status": r.status, **r.payload} for r in found
            if kind is None or r.payload["kind"] == kind]


def task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(models.tasks.c.plan_id == plan_id,
                                                       models.tasks.c.instance_key == key)).one()


def make_plan(engine):
    k = kernel(engine)
    return k, k.create_plan(counsellor_contract(), draft())


def test_plan_created_and_student_needed_and_step_done(engine, on):
    k, ref = make_plan(engine)
    assert [r["kind"] for r in rows(engine)] == ["plan_created"]
    a = task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))  # milestone done; "apply" now waits for the student
    apply = task(engine, ref.plan_id, "apply@p1")
    assert [(r["kind"], r["instance_key"]) for r in rows(engine)] == [
        ("plan_created", None), ("step_done", "a"), ("student_needed", "apply@p1")]
    assert k.complete_student_task(apply.id, "stu-1", {})
    kinds = [(r["kind"], r["instance_key"]) for r in rows(engine)]
    assert kinds[3:] == []  # the student's own tick is never announced, nor is the student step it opens (visa)
    first = rows(engine)[0]
    assert first["key"] == f"os_event:{ref.plan_id}:plan_created:{first['key'].rsplit(':', 1)[1]}"
    assert (first["student_ref"], first["plan_id"], first["schema"]) == ("stu-1", ref.plan_id, "pai.os_event.v1")
    for r in rows(engine):
        OsEventV1.model_validate({k_: v for k_, v in r.items() if k_ != "status"})  # a valid contract each


def test_each_kind_is_emitted_once_at_its_point(engine, on):
    k, ref = make_plan(engine)
    # revised: a changed contract is a revision
    two = counsellor_contract(refs=("p1", "p2"))
    k.create_plan(two, draft(refs=("p1", "p2")))  # same plan, new programmes: a revision
    assert len(rows(engine, "plan_revised")) == 1
    # paused
    assert k.pause_plan(ref.plan_id, "consent_missing")
    assert not k.pause_plan(ref.plan_id, "consent_missing")  # already paused: nothing changes, nothing sent
    assert len(rows(engine, "plan_paused")) == 1
    assert k.resume_plan(ref.plan_id)
    assert len(rows(engine, "plan_paused")) == 1  # resuming has no kind
    # stopped
    k.close_plan(ref.plan_id, "superseded:9")
    k.close_plan(ref.plan_id, "superseded:9")  # again: no second event
    assert len(rows(engine, "plan_stopped")) == 1
    keys = [r["key"] for r in rows(engine)]
    assert len(keys) == len(set(keys))


def test_notice_step_is_never_announced(engine, on):
    k, ref = make_plan(engine)
    two = counsellor_contract(refs=("p1", "p2"))
    k.create_plan(two, draft(refs=("p1", "p2")))  # same plan, new programmes: a revision
    with engine.connect() as conn:
        notice = conn.execute(select(models.tasks).where(models.tasks.c.plan_id == ref.plan_id,
                                                         models.tasks.c.instance_key.like("plan_updated@%"))).one()
    assert notice.state == "waiting_student"
    assert all(r["instance_key"] is None or not r["instance_key"].startswith("plan_updated@") for r in rows(engine))


def test_plan_finished_once(engine, on):
    k, ref = make_plan(engine)
    a = task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    assert k.complete_student_task(task(engine, ref.plan_id, "apply@p1").id, "stu-1", {})
    assert rows(engine, "plan_finished") == []
    assert k.complete_student_task(task(engine, ref.plan_id, "visa").id, "stu-1", {})
    with engine.connect() as conn:
        assert conn.execute(select(models.plans.c.status).where(models.plans.c.id == ref.plan_id)).scalar() == "done"
    assert len(rows(engine, "plan_finished")) == 1
    assert rows(engine)[-1]["kind"] == "plan_finished"


def test_deadline_at_risk_once(engine, on):
    k, ref = make_plan(engine)
    apply = task(engine, ref.plan_id, "apply@p1")
    with engine.begin() as conn:
        conn.execute(update(models.tasks).where(models.tasks.c.id == apply.id).values(
            critical=True, slack_days=-2, latest_finish=datetime(2027, 7, 1, tzinfo=timezone.utc)))
    assert replan_events.detect_at_risk(engine, "pai", ref.plan_id) == 1
    assert replan_events.detect_at_risk(engine, "pai", ref.plan_id) == 0  # the same risk is not announced twice
    got = rows(engine, "deadline_at_risk")
    assert [r["instance_key"] for r in got] == ["apply@p1"]


def test_proposal_waiting_only_when_pending(engine, on):
    k, ref = make_plan(engine)
    store = ProposalStore(engine, "pai")
    store.create(ref.plan_id, [], "rules", [], [], big=False, expires_at=None, status="applied")
    assert rows(engine, "proposal_waiting") == []
    pid = store.create(ref.plan_id, [], "rules", [], [], big=False, expires_at=None)
    got = rows(engine, "proposal_waiting")
    assert [r["key"] for r in got] == [f"os_event:{ref.plan_id}:proposal_waiting:{pid}"]


@pytest.mark.standalone
def test_module_off_emits_nothing(engine, clean):
    manifest.set_enabled(engine, "pai", False)
    k, ref = make_plan(engine)
    a = task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    k.pause_plan(ref.plan_id, "consent_missing")
    ProposalStore(engine, "pai").create(ref.plan_id, [], "rules", [], [], big=False, expires_at=None)
    assert rows(engine) == []


@pytest.mark.standalone
def test_module_row_missing_emits_nothing(engine, clean):
    make_plan(engine)
    assert rows(engine) == []


def test_self_serve_plan_emits_nothing(engine, on):
    k = kernel(engine)
    ref = k.create_plan(contract(), draft())  # source self_serve: no Counsellor student to tell
    k.pause_plan(ref.plan_id, "consent_missing")
    assert rows(engine) == []


def test_emit_twice_with_same_number_is_skipped(engine, on):
    k, ref = make_plan(engine)
    now = datetime(2027, 3, 1, tzinfo=timezone.utc)
    with engine.begin() as conn:
        first = os_events.emit(conn, "pai", ref.plan_id, "plan_paused", 77, now)
        again = os_events.emit(conn, "pai", ref.plan_id, "plan_paused", 77, now)
    assert (first, again) == (True, False)
    assert len([r for r in rows(engine, "plan_paused")]) == 1


def test_change_and_event_are_one_transaction(engine, on):
    k, ref = make_plan(engine)
    before = len(rows(engine))
    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            os_events.emit(conn, "pai", ref.plan_id, "plan_paused", 5, datetime(2027, 3, 1, tzinfo=timezone.utc))
            raise RuntimeError("the change failed")
    assert len(rows(engine)) == before  # rolled back with the change


def test_decision_version_comes_from_the_plan_intake(engine, on):
    k, ref = make_plan(engine)
    with engine.begin() as conn:
        conn.execute(insert(models.counsellor_intake).values(
            tenant_id="pai", decision_id="d-1", student_ref="stu-1", journey_id="j-1", export={}, export_sha256="0",
            chosen_at=datetime(2027, 3, 1, tzinfo=timezone.utc), status="planned", plan_id=ref.plan_id,
            decision_version=3))
    k.pause_plan(ref.plan_id, "consent_missing")
    assert rows(engine, "plan_paused")[0]["decision_version"] == 3
    assert rows(engine, "plan_created")[0]["decision_version"] is None


@pytest.fixture
def svc(engine, clean, os_db):
    s = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine)
    manifest.set_enabled(engine, "pai", True)
    ports.configure(s)
    try:
        yield s
    finally:
        ports.configure(None)


def test_escalation_reader_ignores_os_events(engine, svc):
    k, ref = make_plan(engine)
    k.pause_plan(ref.plan_id, "consent_missing")
    assert rows(engine)  # os_event rows sit in the channel
    assert pending_counsellor_escalations() == []  # and do not break or appear in the escalation reader
    mark_counsellor_delivery("os_event:1:plan_paused:1", "sent")  # an os_event key is never an escalation mark: no-op
    assert all(r["status"] == "pending" for r in rows(engine))


def test_pending_events_and_mark_delivery(engine, svc):
    k, ref = make_plan(engine)
    k.pause_plan(ref.plan_id, "consent_missing")
    got = os_events.pending_events()
    assert [e.kind for e in got] == ["plan_created", "plan_paused"]
    os_events.mark_event_delivery(got[0].key, "sent")
    os_events.mark_event_delivery(got[1].key, "refused")
    assert [e.kind for e in os_events.pending_events()] == []
    assert [r["status"] for r in rows(engine)] == ["sent", "skipped"]


def test_outbox_sender_ignores_os_events(engine, svc):
    k, ref = make_plan(engine)
    sent = []

    class Spy:
        def send(self, message):
            sent.append(message)

    assert Outbox(engine, "pai").deliver(Spy()) == 0
    assert sent == [] and all(r["status"] == "pending" for r in rows(engine))


def test_student_step_open_at_creation_is_not_announced(engine, on):
    pb = playbook(extra_tasks=[{"template_key": "first", "task_type": "student.act", "title": "First",
                                "kind": "student", "inbox_kind": "act"}])
    k = kernel(engine)
    ref = k.create_plan(counsellor_contract(), draft(pb))
    assert task(engine, ref.plan_id, "first").state == "waiting_student"
    assert [r["kind"] for r in rows(engine)] == ["plan_created"]  # plan_created stands for the first revision
    k.pause_plan(ref.plan_id, "consent_missing")
    k.resume_plan(ref.plan_id)
    assert [r["kind"] for r in rows(engine)] == ["plan_created", "plan_paused"]


def test_only_work_steps_say_done_and_only_student_steps_say_needed(engine, on):
    k, ref = make_plan(engine)
    a = task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    for r in rows(engine, "step_done"):
        assert task(engine, ref.plan_id, r["instance_key"]).kind == "work"
    for r in rows(engine, "student_needed"):
        assert task(engine, ref.plan_id, r["instance_key"]).kind == "student"


def test_a_students_own_tick_does_not_announce_the_next_student_step(engine, on):
    pb = playbook(extra_tasks=[{"template_key": "first", "task_type": "student.act", "title": "First",
                                "kind": "student", "inbox_kind": "act"},
                               {"template_key": "second", "task_type": "student.act", "title": "Second",
                                "kind": "student", "inbox_kind": "act", "depends_on": [{"key": "first"}]}])
    k = kernel(engine)
    ref = k.create_plan(counsellor_contract(), draft(pb))
    first = task(engine, ref.plan_id, "first")
    assert first.state == "waiting_student" and task(engine, ref.plan_id, "second").state != "waiting_student"
    before = len(rows(engine, "student_needed"))
    assert k.complete_student_task(first.id, "stu-1", {}) is True
    assert task(engine, ref.plan_id, "second").state == "waiting_student"
    assert len(rows(engine, "student_needed")) == before  # the student just acted: no "needed" for the next step


def test_skip_stale_events_marks_only_old_pending_rows_in_one_statement(engine, svc):
    from datetime import timedelta
    k, ref = make_plan(engine)
    k.pause_plan(ref.plan_id, "consent_missing")
    old = (datetime.now(timezone.utc) - timedelta(hours=60)).isoformat()
    with engine.begin() as conn:  # age the first event only
        first = conn.execute(select(O.c.id, O.c.payload).where(O.c.template == "os_event").order_by(O.c.id)).first()
        conn.execute(update(O).where(O.c.id == first.id).values(payload={**first.payload, "at": old}))
    assert os_events.skip_stale_events(timedelta(hours=48)) == 1
    assert [r["status"] for r in rows(engine)] == ["skipped", "pending"]
    assert os_events.skip_stale_events(timedelta(hours=48)) == 0  # nothing pending is old now
    assert [e.kind for e in os_events.pending_events()] == ["plan_paused"]
