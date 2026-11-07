# ruff: noqa: F811, SIM117
"""P1-T10 Task D2 (R-12): a crash at any P1 hand-off point loses nothing and duplicates nothing. Counsellor on SQLite,
the real OS on Postgres, faults injected by patching the named step to raise. Fictional students only.

Matrix: channel x kill point -> the test that proves it. "covered" is a test that already existed; "new" is added here
(or in `test_connect_crash_p1_requests.py`, which needs the T8 world fixtures, whose names clash with this file's).

| Channel | Kill point | Proof |
|---|---|---|
| Decision (T2) | before the commit | covered: `test_handoff_crash.py::test_a_failure_before_the_commit_loses_and_sends_nothing` |
| Decision (T2) | committed, not delivered | covered: `test_handoff_crash.py::test_a_commit_without_delivery_is_delivered_by_the_sweep_once` |
| Decision (T2) | delivered, mark lost | covered: `test_handoff_crash.py::test_a_lost_delivered_mark_is_a_duplicate_not_a_second_decision` |
| Decision (T2) | OS worker dies in the intake | covered: `test_handoff_crash.py::test_a_worker_killed_mid_process_leaves_one_plan`, `test_crash_counsellor_intake.py` |
| Vault event (T4) | the write dies before commit | new: `test_a_vault_write_that_dies_before_the_commit_leaves_no_version_and_no_row` |
| Vault event (T4) | committed, not delivered | new: `test_a_committed_vault_write_is_delivered_by_one_sweep_and_recorded_once` |
| Vault event (T4) | delivered, mark lost | new: `test_a_lost_vault_event_mark_is_a_duplicate_and_one_event` |
| OS event -> notification (T5) | notification committed, `sent` mark lost | new: `test_a_lost_sent_mark_makes_no_second_notification` |
| Request answer (T8) | Vault written, OS close raises | new, in `test_connect_crash_p1_requests.py`: closed by the Vault event, and by the recompile |
| Request answer (T8) | repeat answer | new, in `test_connect_crash_p1_requests.py` |
| Guardian consent version (T3) | agree committed, delivery lost | new: `test_a_guardian_agree_whose_delivery_is_lost_is_delivered_by_the_sweep_once` |
| Guardian consent version (T3) | withdraw committed, delivery lost | new: `test_a_guardian_withdraw_whose_delivery_is_lost_pauses_the_plan_once` |
| Adoption (T6) | the OS cannot take the agreement | new: `test_an_adoption_the_os_cannot_take_writes_nothing_and_can_be_retried` |
| Adoption (T6) | decision committed, delivery lost | new: `test_an_adoption_whose_delivery_is_lost_is_adopted_once_by_the_sweep` |
| Choice request (T6) | after the app commit, before the mark; between revision and settle | covered: `test_choice_request_delivery.py:158, 244` |
| Fact proposal (T7) | lost mark; a crash between confirm and emit | covered: `test_fact_proposals.py:220, 280` |
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import func, insert, select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import NotificationRecord, RouteDecision, VaultVersion
from app.os import models, ports
from app.os.contracts.route_contract import RouteContract
from app.os.eligibility import facts as eligibility_facts
from app.os.eligibility.facts import current_types
from app.os.ports import os_events as os_events_port
from app.pai_c.connect import student_facts as host_facts
from app.security import rate_limit
from app.services import auth_emails
from scripts.counselor_eval_support import StudentSession
from tests.os.test_adoption_flow import own_plan, sources, tasks
from tests.os.test_connect_t3_flow import (
    events_of,
    link_token,
    outbox,
    plans_of,
    public,
    student,
)
from tests.os.test_connect_t3_flow import run_os as run_os_t3
from tests.os.test_connect_t4_flow import (  # noqa: F401 - fixture
    ENTRY_TYPE,
    TENANT,
    os_world,
    vault_rows,
    write,
)
from tests.os.test_connect_t5_flow import (  # noqa: F401
    bell,
    chosen,
    germany_student,
    level,
    run_os,
    svc,
    world,
)
from tests.test_roadmap_api import TOKEN, data
from tests.test_roadmap_choice_api import EMAIL, choose_with, vault

pytestmark = [pytest.mark.req("R-12"), pytest.mark.chaos]

WINTER = {"term": "winter", "year": 2027}
PK_PLACE = [{"ref": "pk-p1", "rank": 1}]


def count(engine, table, *where) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def pending_then(real, fail_first=1):
    """A stand-in for `deliver_pending` that raises on its first calls (the request died after its commit)."""
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= fail_first:
            raise RuntimeError("the process stopped before the delivery")
        return real(*args, **kwargs)

    return wrapper


# --- 1. Vault event (T4) ---------------------------------------------------------------------------------------

def vault_world(os_world, db, ws):
    """A self-serve plan on the fake Pakistan route and the first Vault facts, delivered: the baseline."""
    ports.configure(os_world.svc, student_facts=lambda ref: host_facts.build(db, ref))
    eligibility_facts.configure_types(current_types() | {"entry_test": ENTRY_TYPE})
    plan_id = os_world.svc.plans.start_plan(RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{ws}", "student_ref": ws,
        "origin_country": "PK", "destination_country": "PK", "level": "bachelor",
        "target_intake": WINTER, "programmes": [{"programme_ref": "p-easy", "rank": 1}]})).plan_id
    first = write(db, ws, "student_record", "education",
                  {"qualification_name": "FSc", "institution_name": "A College", "academic_status": "completed",
                   "result": {"marks_obtained": 1000, "marks_total": 1100}})
    assert bridge.deliver_pending(db, ws)["delivered"] == 1
    return plan_id, first


def fact_events(engine, plan_id) -> list[int]:
    with engine.connect() as conn:
        return [p["vault_version"] for p in conn.execute(select(models.events.c.payload).where(
            models.events.c.type == "student_fact_changed", models.events.c.plan_id == plan_id)
            .order_by(models.events.c.id)).scalars()]


def vault_version(db, ws) -> int:
    db.expire_all()
    row = db.get(VaultVersion, ws)
    return row.version if row else 0


def test_a_vault_write_that_dies_before_the_commit_leaves_no_version_and_no_row(os_world):
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler

    with StudentSession() as student_, student_.factory() as db, patch.object(config, "CONNECT_STUDENT_FACTS", True,
                                                                              create=True):
        ws = student_.workspace_id
        plan_id, first = vault_world(os_world, db, ws)
        version, rows = vault_version(db, ws), len(vault_rows(db, ws))
        candidate = MemoryCandidateService(db).propose(
            ws, "student_record", key="education", proposed_value={"result": {"marks_obtained": 800}},
            entities={"record_id": db.get(type(first), first.id).result_id}, confidence=0.9,
            source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            evidence={"quote": "q", "capture": "details"})
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.rollback()  # the request died before its commit: the write, the version and the row go together
        assert vault_version(db, ws) == version and len(vault_rows(db, ws)) == rows
        assert bridge.sweep_once(db)["submitted"] == 0
        assert fact_events(os_world.engine, plan_id) == [1]
        assert count(os_world.engine, models.events, models.events.c.type == "student_fact_changed") == 1


def test_a_committed_vault_write_is_delivered_by_one_sweep_and_recorded_once(os_world):
    with StudentSession() as student_, student_.factory() as db, patch.object(config, "CONNECT_STUDENT_FACTS", True,
                                                                              create=True):
        ws = student_.workspace_id
        plan_id, first = vault_world(os_world, db, ws)
        write(db, ws, "student_record", "education", {"result": {"marks_obtained": 900}},
              entities={"record_id": db.get(type(first), first.id).result_id})  # committed; no delivery ran
        (_, pending) = vault_rows(db, ws)
        assert pending.status == "pending" and fact_events(os_world.engine, plan_id) == [1]
        assert bridge.sweep_once(db)["submitted"] == 1
        assert bridge.sweep_once(db)["submitted"] == 0  # a second sweep finds nothing to do
        assert fact_events(os_world.engine, plan_id) == [1, 2]
        assert [r.status for r in vault_rows(db, ws)] == ["delivered", "delivered"]


def test_a_lost_vault_event_mark_is_a_duplicate_and_one_event(os_world):
    with StudentSession() as student_, student_.factory() as db, patch.object(config, "CONNECT_STUDENT_FACTS", True,
                                                                              create=True):
        ws = student_.workspace_id
        plan_id, first = vault_world(os_world, db, ws)
        write(db, ws, "student_record", "education", {"result": {"marks_obtained": 900}},
              entities={"record_id": db.get(type(first), first.id).result_id})
        with patch.object(db, "commit", side_effect=RuntimeError("the mark could not be saved")):
            with pytest.raises(RuntimeError):
                bridge.deliver_pending(db, ws)  # PAI OS took the event; the mark did not reach the database
        db.rollback()
        assert vault_rows(db, ws)[-1].status == "pending" and fact_events(os_world.engine, plan_id) == [1, 2]
        assert bridge.sweep_once(db)["submitted"] == 1  # redelivered: the OS says `duplicate`
        assert fact_events(os_world.engine, plan_id) == [1, 2]  # still one event per version (uq_os_vault_events_version)
        assert vault_rows(db, ws)[-1].status == "delivered"
        with os_world.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(models.vault_events)).scalar_one() == 2


# --- 2. OS event -> notification (T5) --------------------------------------------------------------------------

def notifications(who, kind) -> int:
    with who.factory() as db:
        return db.scalar(select(func.count()).select_from(NotificationRecord).where(
            NotificationRecord.dedupe_key.like(f"%:{kind}:%")))


def test_a_lost_sent_mark_makes_no_second_notification(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"):
        vault((client, who, params))
        data(choose_with(client, params, destination="DE", places=[{"ref": "ovgu-eeit", "rank": 1}], intake=WINTER))
        assert run_os(svc_) == [("planned", None)]
        real = os_events_port.mark_event_delivery
        with patch.object(os_events_port, "mark_event_delivery", side_effect=RuntimeError("mark lost")):
            with who.factory() as db, pytest.raises(RuntimeError):
                bridge.deliver_os_events(db)  # the notification is committed; the OS never heard "sent"
        assert notifications(who, "plan_created") == 1
        with who.factory() as db:
            first = bridge.deliver_os_events(db)  # the next sweep sees the event pending again
            bridge.deliver_os_events(db)
        assert first["sent"] >= 1 and notifications(who, "plan_created") == 1  # the dedupe key held
        assert [k for k, _ in bell(who)].count("plan_created") == 1
        assert real is os_events_port.mark_event_delivery


# --- 4. Guardian consent version (T3) --------------------------------------------------------------------------

@pytest.fixture
def guardian_world(svc, engine, monkeypatch):
    """PAI OS on its ports, the Counsellor module on, the hand-off on, the mailer stubbed. Yields the sent mails."""
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(svc)
    rate_limit.reset()
    mails = []
    monkeypatch.setattr(auth_emails, "send_email",
                        lambda to, subject, html, text_body=None: mails.append({"to": to, "text": text_body}) or True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    with patch.object(config, "CONNECT_HANDOFF", True, create=True):
        try:
            yield mails
        finally:
            ports.configure(None)
            rate_limit.reset()


def test_a_guardian_agree_whose_delivery_is_lost_is_delivered_by_the_sweep_once(svc, guardian_world):
    mails = guardian_world
    with student(dob="2012-05-05") as (client, who, params):
        data(choose_with(client, params, destination="PK", places=PK_PLACE, intake=WINTER, guardian_email=EMAIL))
        assert run_os_t3(svc) == [("held", "consent_missing")]
        token = link_token(mails[0])
        with patch("app.pai_os_bridge.deliver_pending", side_effect=RuntimeError("the process stopped")):
            assert public(client, "post", f"{token}/agree")["state"] == "agreed"  # committed; delivery lost
        assert outbox(who)[-1] == ("pending", None) and run_os_t3(svc) == [] and plans_of(svc, who) == []
        with who.factory() as db:
            assert bridge.sweep_once(db)["submitted"] == 1
            assert bridge.sweep_once(db)["submitted"] == 0
        assert run_os_t3(svc) == [("planned", None)]
        assert run_os_t3(svc) == [] and len(plans_of(svc, who)) == 1
        assert public(client, "post", f"{token}/agree") == {"state": "used"}  # a link is single use
        assert run_os_t3(svc) == [] and len(plans_of(svc, who)) == 1
        assert [o[0] for o in outbox(who)] == ["delivered"] * len(outbox(who))


def test_a_guardian_withdraw_whose_delivery_is_lost_pauses_the_plan_once(svc, guardian_world):
    mails = guardian_world
    with student(dob="2012-05-05") as (client, who, params):
        data(choose_with(client, params, destination="PK", places=PK_PLACE, intake=WINTER, guardian_email=EMAIL))
        run_os_t3(svc)
        public(client, "post", f"{link_token(mails[0])}/agree")
        assert run_os_t3(svc) == [("planned", None)]
        (plan,) = plans_of(svc, who)
        withdraw = link_token(mails[1])
        with patch("app.pai_os_bridge.deliver_pending", side_effect=RuntimeError("the process stopped")):
            assert public(client, "post", f"{withdraw}/withdraw") == {"state": "withdrawn"}
        assert run_os_t3(svc) == [] and plans_of(svc, who)[0].status == "active"  # the OS has not heard yet
        with who.factory() as db:
            assert bridge.sweep_once(db)["submitted"] == 1
        assert run_os_t3(svc) == [("paused", "consent_missing")]
        assert run_os_t3(svc) == [] and events_of(svc, plan.id) == ["plan_paused"]
        assert public(client, "post", f"{withdraw}/withdraw") == {"state": "used"}
        assert plans_of(svc, who)[0].status == "paused" and len(plans_of(svc, who)) == 1


# --- 5. Adoption (T6) ------------------------------------------------------------------------------------------

@contextmanager
def adoption_world(world_):
    svc_ = world_
    with germany_student() as (client, who, params), level("master"), \
            patch.object(config, "CONNECT_MY_PLAN", True, create=True):
        vault((client, who, params))
        plan_id = own_plan(svc_, who.workspace_id)  # the student's own plan, built before they chose
        data(choose_with(client, params, destination="DE", places=[{"ref": "ovgu-eeit", "rank": 1}], intake=WINTER))
        assert run_os(svc_) == [("refused", "self_serve_plan_open")]
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                        choice_sink_enabled=bridge.choice_enabled)
        yield client, who, params, plan_id, tasks(svc_, plan_id)


def versions(who) -> list[int]:
    with who.factory() as db:
        return list(db.scalars(select(RouteDecision.decision_version).where(
            RouteDecision.workspace_id == who.workspace_id).order_by(RouteDecision.decision_version)))


def test_an_adoption_the_os_cannot_take_writes_nothing_and_can_be_retried(world):
    svc_ = world
    with adoption_world(world) as (client, who, params, plan_id, before):
        with patch.object(bridge.plan_source, "request_adoption", side_effect=RuntimeError("the OS stopped")):
            refused = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert refused.status_code == 503 and versions(who) == [1]  # no decision for an agreement the OS did not take
        assert run_os(svc_) == [] and sources(svc_) == {"self_serve": 1}
        posted = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert data(posted) == {"state": "linking", "decision_version": 2}
        assert run_os(svc_) == [("revised", None)]
        assert sources(svc_) == {"counsellor": 1} and tasks(svc_, plan_id) == before and versions(who) == [1, 2]


def test_an_adoption_whose_delivery_is_lost_is_adopted_once_by_the_sweep(world):
    svc_ = world
    with adoption_world(world) as (client, who, params, plan_id, before):
        with patch.object(bridge, "deliver_pending", pending_then(bridge.deliver_pending)):
            posted = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert data(posted) == {"state": "linking", "decision_version": 2}  # committed; the delivery died
        assert outbox(who)[-1] == ("pending", None) and run_os(svc_) == []
        assert sources(svc_) == {"self_serve": 1}  # nothing adopted yet
        with who.factory() as db:
            assert bridge.sweep_once(db)["submitted"] >= 1
            assert bridge.sweep_once(db)["submitted"] == 0
        assert run_os(svc_) == [("revised", None)] and run_os(svc_) == []
        assert sources(svc_) == {"counsellor": 1} and tasks(svc_, plan_id) == before
        again = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert data(again) == {"state": "linked", "decision_version": 2}  # a repeat after the adoption: no version 3
        assert versions(who) == [1, 2] and run_os(svc_) == []
        with svc_.engine.connect() as conn:
            assert conn.execute(select(models.plans.c.id)).scalars().all() == [plan_id]  # no second plan
