"""Slice 8 Task 7: route problems go to the Counsellor (spec §2.5, S8-D12). Only with the module on, only for
Counsellor plans, only route problems; sent once through the outbox; the note is a fixed sentence. Fictional."""

import json

import pytest
from sqlalchemy import insert, select

from app.os import models, ports
from app.os.adapters.counsellor.escalation import load_notes, reason_for
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.services import make_services
from app.os.outbox import Outbox
from app.os.outbox.senders import LogSender
from app.os.ports.escalation import mark_counsellor_delivery, pending_counsellor_escalations
from app.os.replan import events
from app.os.replan.apply import BROKEN_REASON, LIMIT_REASON, REFUSED_REASON
from app.os.replan.rules import REASONS
from app.os.replan.run import BUDGET_REASON, INVALID_REASON
from app.os.replan.store import SupportStore
from app.os.settings import load_settings

O = models.outbox
SUPERVISOR = "Supervisor: the family said the fee is too high for them"  # free text: never sent


@pytest.fixture
def svc(engine, clean, os_db):
    s = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine)
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(s)
    try:
        yield s
    finally:
        ports.configure(None)


def plan(svc, source="counsellor", student="ws-1") -> int:
    ref = "j-1:DE:master" if source == "counsellor" else f"self-{student}"
    with svc.engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source=source, external_ref=ref, student_ref=student, contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def event(svc, plan_id: int, type_: str, n: int = 1) -> int:
    with svc.engine.begin() as conn:
        return events.record(conn, "pai", plan_id, type_, {}, f"test-{n}")


def sent(svc) -> list[dict]:
    with svc.engine.connect() as conn:
        return [{"key": r.idempotency_key, **r.payload} for r in conn.execute(
            select(O).where(O.c.channel == "counsellor").order_by(O.c.id)).all()]


def escalate(svc, type_: str, reason: str, source: str = "counsellor") -> int:
    p = plan(svc, source)
    return svc.escalations.escalate(p, [event(svc, p, type_)], reason)


@pytest.mark.parametrize("type_,reason,expected", [
    ("route_invalid", BROKEN_REASON, "not_eligible"),
    ("admission_rejected", SUPERVISOR, "all_rejected"),
    ("deadline_at_risk", REASONS["late"], "deadline_passed"),
    ("escalate", SUPERVISOR, "blocking_gap"),
    ("document_missing", SUPERVISOR, "blocking_gap"),
])
def test_route_problem_reasons(svc, type_, reason, expected):
    cid = escalate(svc, type_, reason)
    (row,) = sent(svc)
    assert (row["key"], row["schema"], row["case_id"], row["reason"]) == (
        f"escalation:{cid}", "pai.escalation.v1", cid, expected)
    assert (row["journey_id"], row["student_ref"], row["note"]) == ("j-1", "ws-1", load_notes()[expected])
    case = SupportStore(svc.engine, "pai").get(cid)
    assert (case.counsellor_status, case.counsellor_reason, case.status) == ("pending", expected, "open")


def test_route_invalid_is_not_eligible():
    assert reason_for("route_invalid", BROKEN_REASON) == "not_eligible"
    assert reason_for("admission_rejected", f"{BROKEN_REASON} (no deadline)") == "not_eligible"  # no longer compiles


def test_intake_refusal_is_other(svc):
    from app.os.adapters.counsellor.escalation import intake_refused

    store = IntakeStore(svc.engine, "pai")
    store.add({"decision_id": "d-1", "journey_id": "j-1", "student_ref": "ws-1",
               "chosen_at": "2027-01-10T09:00:00+05:00"}, "0" * 64)
    intake_refused(svc.engine, "pai", store.get("d-1"))
    intake_refused(svc.engine, "pai", store.get("d-1"))  # a repeat: still one row
    (row,) = sent(svc)
    assert (row["key"], row["case_id"], row["reason"], row["journey_id"]) == ("escalation:intake:d-1", None, "other",
                                                                             "j-1")
    assert store.get("d-1").counsellor_status == "pending"


@pytest.mark.parametrize("type_,reason", [
    ("admission_rejected", LIMIT_REASON),  # the daily-change limit
    ("task_failed", REASONS["failed"]),  # a step failing twice
    ("admission_rejected", "No automatic change: a rejection left 0 programme(s) and there is no close match."),
    ("deadline_at_risk", BUDGET_REASON),  # the Supervisor over budget
    ("escalate", INVALID_REASON),  # or invalid
    ("deadline_at_risk", REFUSED_REASON),  # every operation refused
    ("document_missing", "The plan kept changing while this change was being made."),  # a stale draft
    ("playbook_newer", SUPERVISOR),
])
def test_system_problems_not_sent(svc, type_, reason):
    cid = escalate(svc, type_, reason)
    assert sent(svc) == [] and SupportStore(svc.engine, "pai").get(cid).counsellor_status is None


def test_self_serve_case_not_sent(svc):
    escalate(svc, "escalate", SUPERVISOR, source="self_serve")  # review focus 4
    assert sent(svc) == []


def test_intake_support_cases_not_sent(svc):
    p = plan(svc)
    with svc.engine.begin() as conn:
        eid = conn.execute(insert(models.events).values(tenant_id="pai", plan_id=p, type="counsellor_intake",
                                                        payload={"decision_id": "d-1"}).returning(models.events.c.id)
                           ).scalar_one()
    svc.escalations.escalate(p, [eid], "A Counsellor decision names a route whose plan was closed: a person decides.")
    svc.escalations.escalate(p, [], "no event at all")
    assert sent(svc) == []


def test_module_off_not_sent(svc):
    with svc.engine.begin() as conn:
        conn.execute(models.modules.update().values(enabled=False))
    cid = escalate(svc, "escalate", SUPERVISOR)
    assert sent(svc) == [] and SupportStore(svc.engine, "pai").get(cid).status == "open"  # the case is still opened


def test_sent_once(svc):
    p = plan(svc)
    e = event(svc, p, "escalate")
    first = svc.escalations.escalate(p, [e], SUPERVISOR)
    assert svc.escalations.escalate(p, [e], SUPERVISOR) == first
    assert len(sent(svc)) == 1


def test_note_never_supervisor_reason(svc):
    escalate(svc, "admission_rejected", SUPERVISOR)
    text = json.dumps(sent(svc))
    assert "family" not in text and "Supervisor" not in text


def test_pending_and_delivery_marks(svc):
    cid = escalate(svc, "escalate", SUPERVISOR)
    (pending,) = pending_counsellor_escalations()
    assert (pending.key, pending.reason) == (f"escalation:{cid}", "blocking_gap")
    mark_counsellor_delivery(pending.key, "sent")
    assert pending_counsellor_escalations() == []
    assert SupportStore(svc.engine, "pai").get(cid).counsellor_status == "sent"


def test_refused_delivery_keeps_case_open(svc):
    cid = escalate(svc, "escalate", SUPERVISOR)
    mark_counsellor_delivery(f"escalation:{cid}", "refused", "The journey is no longer at a decision stage.")
    case = SupportStore(svc.engine, "pai").get(cid)
    assert (case.status, case.counsellor_status) == ("open", "refused")
    assert pending_counsellor_escalations() == []
    with svc.engine.connect() as conn:
        row = conn.execute(select(O).where(O.c.idempotency_key == f"escalation:{cid}")).one()
    assert row.status == "skipped" and row.payload["delivery"]["reason"].startswith("The journey")


def test_email_sender_skips_counsellor_rows(svc):
    escalate(svc, "escalate", SUPERVISOR)
    assert Outbox(svc.engine, "pai").deliver(LogSender(svc.engine, "pai")) == 0  # the glue delivers them, not email
    assert len(pending_counsellor_escalations()) == 1


def test_notes_checked(tmp_path):
    assert set(load_notes()) == {"not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other"}
    bad = tmp_path / "notes.yaml"
    bad.write_text("not_eligible: A sentence.\n")
    with pytest.raises(ValueError, match="all_rejected"):
        load_notes(bad)


def test_admin_support_list_fields(svc):
    from app.os.api.replan import case_fields

    cid = escalate(svc, "escalate", SUPERVISOR)
    got = case_fields(SupportStore(svc.engine, "pai").get(cid))
    assert (got["counsellor_status"], got["counsellor_reason"]) == ("pending", "blocking_gap")
