"""P3-T7 (master R-39, ADR-001 D12): the six R-39 replan events, found from registry and Knowledge fact changes and from
the student's answers, each with its reaction: recorded and closed, no plan change of its own (the master spec gives none);
a changed date revises the plan through row 6.10's recompile, under the compiler's trust rules. Nothing goes to chat
(R-45). Real service, kernel and Postgres. Fictional board, calendar, route, programme and student; no real date."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select, update

from app.os import models
from app.os.adapters.counsellor import manifest
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.changes import after_fact_change
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.registry.calendars import record_calendar, record_calendar_date
from app.os.registry.model import RegistryEntry
from app.os.registry.store import RegistryStore
from app.os.replan import detectors, event_texts
from app.os.replan import events as ev
from app.os.replan.apply import Replanner
from app.os.replan.config import ReplanConfig
from app.os.replan.rules import RECORD_ONLY, Handover, rules_for
from app.os.replan.run import run_replan_job
from app.os.requests.state import StudentState
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.registry.helpers import AT, child, olist
from tests.os.test_compile_needs import contract

R39 = ("merit_list.published", "merit_list.not_listed", "merit_list.next_round", "fee_deposit.due",
       "test.result_published", "admission.schedule_changed")
BOOKS = load_playbook_dir(Path(__file__).parent / "playbooks" / "calendar")
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
CAL = "cal:alpha-results"
URL = "https://results.alpha.test/calendar"
MERIT = "merit_list@p1"
EV, T, PR, O, RV = models.events, models.tasks, models.proposals, models.outbox, models.plan_revisions

pytestmark = [pytest.mark.req("R-39"), pytest.mark.req("R-45")]


class Clock:
    day = date(2027, 3, 1)

    def __call__(self):
        return self.day


@pytest.fixture
def world(engine, clean, monkeypatch):
    monkeypatch.setattr("app.os.service.state.build", lambda plans, student_ref, *a, **k: StudentState())
    clock = Clock()
    kernel, kb = Kernel(engine, "pai"), SqlKnowledge(engine, "pai")
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), kernel, kb, dict(BOOKS), today=clock)
    registry = RegistryStore(engine, "pai")
    registry.record(olist(), cause="import")
    registry.record(child("admission_body", "body", "alpha-board", None, region="national"), cause="import")
    record_calendar(registry, RegistryEntry(
        entity_id=CAL, kind="calendar", name="Alpha board result calendar", parent_id="body:alpha-board",
        source_url=URL, quote="Results are announced as below", checked_at=AT), "result", cause="import")
    merit(kb, "2027-08-15")
    manifest.set_enabled(engine, "pai", True)  # the Counsellor module is on: an os_event row would be written if any
    replanner = Replanner(engine, svc, {}, Outbox(engine, "pai"), clock=lambda: datetime(2027, 3, 1, tzinfo=timezone.utc))
    plan = svc.start_plan(contract().model_copy(update={"source": "counsellor"}), with_needs=True).plan_id
    return svc, kb, kernel, registry, clock, replanner, plan


def merit(kb, day: str, status="confirmed") -> int:
    return kb.upsert("programme", "p1", "merit_list_date", Fact(
        {"date": day}, "Merit list on this day" if status == "confirmed" else "", URL, CHECKED, 2027, status))


def change(svc, kernel, fid: int, status="confirmed", scope="programme", ref="p1", field="merit_list_date") -> list[int]:
    return after_fact_change(svc, kernel, scope, ref, field, fid, status, 2027, complete=status == "confirmed")


def of(engine, plan_id, type_=None) -> list:
    with engine.connect() as conn:
        q = select(EV).where(EV.c.plan_id == plan_id, EV.c.type.in_(R39) if type_ is None else EV.c.type == type_)
        return conn.execute(q.order_by(EV.c.id)).all()


def task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(T).where(T.c.plan_id == plan_id, T.c.instance_key == key)).first()


def count(engine, table, plan_id=None) -> int:
    with engine.connect() as conn:
        q = select(func.count()).select_from(table)
        if plan_id is not None:
            q = q.where(table.c.plan_id == plan_id)
        return conn.execute(q).scalar()


def react(replanner, plan_id: int, event_id: int):
    """The `os.replan` workflow's rules and decide steps for one event."""
    e = ev.get(replanner.engine, "pai", event_id)
    got = rules_for(e, replanner.state(plan_id), ReplanConfig())
    assert not isinstance(got, Handover), got
    return got, replanner.decide(plan_id, [event_id], "rules", got)


# ------------------------------------------------------------------ the list and the trigger data


def test_the_six_r39_types_are_replan_events_and_none_more():
    assert set(R39) <= set(ev.EVENT_TYPES) and set(RECORD_ONLY) == set(R39) == set(detectors.R39)
    assert len(ev.EVENT_TYPES) == 9 + 6


def test_triggers_are_fields_and_classes_only():
    trig = detectors.triggers()
    assert trig.merit_list_fields == {"merit_list_date"} and trig.result_fields == {"result_date"}
    assert trig.fee_classes == {"fee"} and trig.schedule_classes == {"schedule_date", "deadline", "test_date"}
    assert dict(trig.answers) == {"merit_list.not_listed": {"choice": "not_listed"}}
    raw = (Path(detectors.__file__).with_name("event_triggers.yaml")).read_text(encoding="utf-8").lower()
    for name in ("sindh", "punjab", "seccap", "board", "karachi", "lahore", "islamabad", "khyber", "germany"):
        assert name not in raw  # no region or body name


@pytest.mark.parametrize("field,cls,old,new,today,want", [
    ("merit_list_date", "schedule_date", None, "2027-08-15", date(2027, 8, 15), ["merit_list.published"]),
    ("merit_list_date", "schedule_date", None, "2027-08-15", date(2027, 8, 14), []),
    ("merit_list_date", "schedule_date", "2027-08-15", "2027-08-20", date(2027, 3, 1), ["admission.schedule_changed"]),
    ("merit_list_date", "schedule_date", "2027-08-15", "2027-08-30", date(2027, 8, 16), ["merit_list.next_round"]),
    ("result_date", "schedule_date", None, {"date": "2027-02-20", "tz": "Asia/Karachi"}, date(2027, 3, 1),
     ["test.result_published"]),
    ("any_fee_due", "fee", None, "2027-09-01", date(2027, 3, 1), ["fee_deposit.due"]),
    ("any_fee_due", "fee", "2027-09-01", "2027-09-01", date(2027, 3, 1), []),
    ("any_fee_amount", "fee", None, 12000, date(2027, 3, 1), []),  # an amount is not a fee date
    ("any_close", "deadline", "2027-05-01", "2027-05-10", date(2027, 3, 1), ["admission.schedule_changed"]),
    ("any_close", "deadline", None, "2027-05-10", date(2027, 3, 1), []),  # a first date is not a change
    ("any_close", "admission_requirement", "2027-05-01", "2027-05-10", date(2027, 3, 1), []),
])
def test_found_is_generic_on_field_and_class(field, cls, old, new, today, want):
    assert [f.type for f in detectors.found(field, cls, old, new, today)] == want


# ------------------------------------------------------------------ each event from its fact change, with its reaction


def test_schedule_changed_is_recorded_and_the_plan_follows_through_6_10(engine, world):
    svc, kb, kernel, _, _, replanner, plan = world
    assert task(engine, plan, MERIT).due_at.date() == date(2027, 8, 15)
    fid = merit(kb, "2027-08-20")
    assert change(svc, kernel, fid) == [plan]  # row 6.10: the plan is revised to the new date
    got = of(engine, plan)
    assert [e.type for e in got] == ["admission.schedule_changed"]
    keys = ("previous", "date", "confirmed", "programme_ref", "field")
    assert {k: got[0].payload[k] for k in keys} == {"previous": "2027-08-15", "date": "2027-08-20", "confirmed": True,
                                                    "programme_ref": "p1", "field": "merit_list_date"}
    t = task(engine, plan, MERIT)
    assert t.due_at.date() == date(2027, 8, 20) and not t.provisional
    revisions = count(engine, RV, plan)
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and d.status == "applied" and count(engine, RV, plan) == revisions  # recorded, nothing more
    assert ev.pending(engine, "pai", plan) == []  # closed: never handed to the Supervisor or a person
    assert change(svc, kernel, fid) == [] and len(of(engine, plan)) == 1  # the same change once


def test_an_unconfirmed_date_does_not_move_the_plan_as_if_confirmed(engine, world):
    svc, kb, kernel, _, _, replanner, plan = world
    fid = merit(kb, "2027-08-25", status="unconfirmed")
    change(svc, kernel, fid, status="unconfirmed")
    got = of(engine, plan)
    assert [(e.type, e.payload["confirmed"]) for e in got] == [("admission.schedule_changed", False)]
    t = task(engine, plan, MERIT)
    assert t.provisional  # the compiler's trust rule: a step dated by an unconfirmed fact is never firm
    assert task(engine, plan, "confirm_fact@p1:merit_list_date") is not None  # and the date is checked
    revisions = count(engine, RV, plan)
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and d.status == "applied" and count(engine, RV, plan) == revisions  # the event moves nothing
    # trust only dropping (same value, now stale) raises nothing new
    kb.set_status(fid, "stale", cause="monitor")
    change(svc, kernel, fid, status="stale")
    assert len(of(engine, plan)) == 1


def test_published_on_the_list_day_from_the_fact_and_from_the_sweep(engine, world):
    svc, kb, kernel, _, clock, replanner, plan = world
    clock.day = date(2027, 8, 15)  # the list day comes: no fact changed, the replan sweep finds it

    class Client:
        queued = []

        def enqueue(self, options, plan_id, event_id):
            self.queued.append((plan_id, event_id))

    run_replan_job(replanner, Client(), datetime(2027, 8, 15, tzinfo=timezone.utc))
    got = of(engine, plan)
    assert [(e.type, e.payload["date"], e.payload["confirmed"]) for e in got] == [
        ("merit_list.published", "2027-08-15", True)]
    assert (plan, got[0].id) in Client.queued
    run_replan_job(replanner, Client(), datetime(2027, 8, 15, tzinfo=timezone.utc))
    assert len(of(engine, plan)) == 1  # once
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and d.status == "applied"
    # a fact written on the day itself gives the same event (deduped)
    fid = merit(kb, "2027-08-15")
    change(svc, kernel, fid)
    assert len(of(engine, plan, "merit_list.published")) == 1


def test_next_round_when_a_later_list_day_follows_one_that_passed(engine, world):
    svc, kb, kernel, _, clock, replanner, plan = world
    clock.day = date(2027, 8, 16)
    fid = merit(kb, "2027-08-30")
    change(svc, kernel, fid)
    got = of(engine, plan)
    assert [(e.type, e.payload["previous"], e.payload["date"]) for e in got] == [
        ("merit_list.next_round", "2027-08-15", "2027-08-30")]  # a round, not a schedule change
    revisions = count(engine, RV, plan)
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and count(engine, RV, plan) == revisions


def test_result_published_from_a_registry_calendar_date(engine, world):
    svc, kb, kernel, registry, _, replanner, plan = world
    fid = record_calendar_date(registry, kb, CAL, "result_date", date(2027, 2, 20), tz="Asia/Karachi", url=URL,
                               quote="Result day", checked_at=CHECKED, intake_year=2027, intake_term="winter",
                               status="confirmed", cause="import")
    change(svc, kernel, fid, scope="registry", ref=CAL, field="result_date")
    got = of(engine, plan)
    assert [(e.type, e.payload["scope"], e.payload["ref"]) for e in got] == [("test.result_published", "registry", CAL)]
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and d.status == "applied"


def test_fee_deposit_due_from_a_dated_fact_of_the_fee_class(engine, world):
    svc, kb, kernel, _, clock, replanner, plan = world
    fid = kb.upsert("programme", "p1", "any_fee_due", Fact("2027-09-01", "Pay by this day", URL, CHECKED, 2027,
                                                           "confirmed", fact_class="fee"))
    assert detectors.on_fact_change(engine, "pai", [plan], "programme", "p1", "any_fee_due", fid, 2027, clock()) == 1
    got = of(engine, plan)
    assert [(e.type, e.payload["date"]) for e in got] == [("fee_deposit.due", "2027-09-01")]
    revisions = count(engine, RV, plan)
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and count(engine, RV, plan) == revisions
    amount = kb.upsert("programme", "p1", "any_fee_amount", Fact(12000, "Fee", URL, CHECKED, 2027, "confirmed",
                                                                 fact_class="fee"))
    assert detectors.on_fact_change(engine, "pai", [plan], "programme", "p1", "any_fee_amount", amount, 2027,
                                    clock()) == 0


def test_not_listed_from_the_students_answer_removes_nothing(engine, world):
    svc, kb, kernel, _, _, replanner, plan = world
    with engine.begin() as conn:
        tid = conn.execute(update(T).where(T.c.plan_id == plan, T.c.instance_key == MERIT)
                           .values(state="waiting_student").returning(T.c.id)).scalar_one()
    assert kernel.complete_student_task(tid, "stu-1", {"choice": "not_listed"})
    got = of(engine, plan)
    assert [(e.type, e.payload["programme_ref"], e.task_id) for e in got] == [("merit_list.not_listed", "p1", tid)]
    assert of(engine, plan, "admission_rejected") == []
    revisions = count(engine, RV, plan)
    ops, d = react(replanner, plan, got[0].id)
    assert ops == [] and count(engine, RV, plan) == revisions  # rounds carry an application forward (SI-08)


def test_another_answer_gives_no_r39_event(engine, world):
    _, _, kernel, _, _, _, plan = world
    with engine.begin() as conn:
        tid = conn.execute(update(T).where(T.c.plan_id == plan, T.c.instance_key == MERIT)
                           .values(state="waiting_student").returning(T.c.id)).scalar_one()
    kernel.complete_student_task(tid, "stu-1", {"choice": "accepted"})
    assert of(engine, plan) == []


# ------------------------------------------------------------------ R-45: no chat, texts are data


def test_no_r39_event_or_reaction_writes_to_the_counsellor_or_any_outbox(engine, world):
    svc, kb, kernel, registry, clock, replanner, plan = world
    before = count(engine, O)
    with engine.begin() as conn:
        tid = conn.execute(update(T).where(T.c.plan_id == plan, T.c.instance_key == MERIT)
                           .values(state="waiting_student").returning(T.c.id)).scalar_one()
    fee = kb.upsert("programme", "p1", "any_fee_due", Fact("2027-09-01", "Pay by", URL, CHECKED, 2027, "confirmed",
                                                           fact_class="fee"))
    detectors.on_fact_change(engine, "pai", [plan], "programme", "p1", "any_fee_due", fee, 2027, clock())
    clock.day = date(2027, 8, 15)
    detectors.detect_reached(engine, "pai", plan, clock())
    fid = merit(kb, "2027-08-30")
    clock.day = date(2027, 8, 16)
    detectors.on_fact_change(engine, "pai", [plan], "programme", "p1", "merit_list_date", fid, 2027, clock())
    with engine.begin() as conn:
        detectors.on_answer(conn, "pai", plan, tid, MERIT, "p1", {"choice": "not_listed"})
    got = of(engine, plan)
    assert {e.type for e in got} == {"fee_deposit.due", "merit_list.published", "merit_list.next_round",
                                     "merit_list.not_listed"}
    for e in got:
        react(replanner, plan, e.id)
    assert count(engine, O) == before  # no os_event row, no message of any channel
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(PR).where(PR.c.plan_id == plan,
                                                                       PR.c.status != "applied")).scalar() == 0
    from app.os.ports.os_events import KINDS

    assert not set(R39) & set(KINDS)  # the Counsellor's event contract has no R-39 kind: nothing to turn into chat


def test_student_texts_are_data_and_wait_for_the_owner():
    raw = yaml.safe_load(event_texts.PATH.read_text(encoding="utf-8"))
    assert raw["approved"] is False and all(isinstance(raw[k], str) and raw[k] for k in R39)

    class Off:
        rehearsal = False

    class On:
        rehearsal = True

    assert event_texts.note("merit_list.published", Off()) is None
    assert event_texts.note("merit_list.published", On()) == raw["merit_list.published"]
    src = "".join(Path(m.__file__).read_text(encoding="utf-8") for m in (detectors, event_texts))
    assert "os_events" not in src and "outbox" not in src.replace("Counsellor's outbox", "")
