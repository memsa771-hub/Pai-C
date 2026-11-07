"""Slice 8 Task 7: route problems go to the Counsellor (spec §2.5, S8-D12). Only with the module on, only for
Counsellor plans, only route problems; sent once through the outbox; the note is a fixed sentence. Fictional."""

import json

import pytest
from sqlalchemy import insert, select

from app.os import models, ports
from app.os.adapters.counsellor.escalation import load_notes, reason_for
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.services import make_services
from app.os.contracts.escalation_v2 import EscalationV2
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
        f"escalation:{cid}", "pai.escalation.v2", cid, expected)  # P1-T6: v2 on the channel
    assert (row["journey_id"], row["student_ref"], row["note"]) == ("j-1", "ws-1", load_notes()[expected])
    case = SupportStore(svc.engine, "pai").get(cid)
    assert (case.counsellor_status, case.counsellor_reason, case.status) == ("pending", expected, "open")


def intake_row(svc, plan_id: int, version: int | None, n: int) -> None:
    with svc.engine.begin() as conn:
        conn.execute(insert(models.counsellor_intake).values(
            tenant_id="pai", decision_id=f"d-{plan_id}-{n}", student_ref="ws-1", journey_id="j-1", export={},
            export_sha256="0" * 64, chosen_at="2027-01-10T09:00:00+05:00", status="planned", plan_id=plan_id,
            decision_version=version))


@pytest.mark.req("R-11")
def test_counsellor_payload_is_escalation_v2(svc):
    p = plan(svc)
    intake_row(svc, p, 2, 1)
    intake_row(svc, p, 4, 2)
    intake_row(svc, p, 3, 3)
    with svc.engine.begin() as conn:
        other = conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref="j-9:DE:master", student_ref="ws-9", contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()
    intake_row(svc, other, 9, 4)  # another plan's version never counts
    cid = svc.escalations.escalate(p, [event(svc, p, "escalate")], SUPERVISOR)
    (row,) = sent(svc)
    assert (row["schema"], row["key"], row["decision_version"]) == ("pai.escalation.v2", f"escalation:{cid}", 4)
    assert (row["reason"], row["note"]) == ("blocking_gap", load_notes()["blocking_gap"])
    assert EscalationV2.model_validate(row | {"key": row["key"]}).decision_version == 4


@pytest.mark.req("R-11")
def test_payload_without_an_applied_version_has_none(svc):
    escalate(svc, "escalate", SUPERVISOR)
    (row,) = sent(svc)
    assert row["schema"] == "pai.escalation.v2" and row["decision_version"] is None


@pytest.mark.req("R-11")
def test_intake_refusal_carries_the_intakes_version(svc):
    from app.os.adapters.counsellor.escalation import intake_refused

    store = IntakeStore(svc.engine, "pai")
    store.add({"decision_id": "d-7", "journey_id": "j-1", "student_ref": "ws-1", "decision_version": 5,
               "chosen_at": "2027-01-10T09:00:00+05:00"}, "0" * 64)
    intake_refused(svc.engine, "pai", store.get("d-7"))
    (row,) = sent(svc)
    assert (row["schema"], row["decision_version"]) == ("pai.escalation.v2", store.get("d-7").decision_version)


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


@pytest.mark.standalone
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


def test_an_os_event_key_never_updates_a_support_case(svc):
    cid = escalate(svc, "escalate", SUPERVISOR)
    mark_counsellor_delivery(f"os_event:{cid}:plan_created:5", "sent")  # same number as the case: still not an escalation
    case = SupportStore(svc.engine, "pai").get(cid)
    assert case.counsellor_status != "sent"
    assert [e.key for e in pending_counsellor_escalations()] == [f"escalation:{cid}"]


@pytest.mark.req("R-11")
def test_student_fact_changed_reaches_counsellor(svc):
    """P1-T6 Task 4 (ruling 11): the R-22 `Escalate(fact_all_below)` arrives as a `student_fact_changed` event and is
    sent as `not_eligible`; it used to map to nothing and never reached the Counsellor."""
    assert reason_for("student_fact_changed", REASONS["fact_all_below"]) == "not_eligible"
    cid = escalate(svc, "student_fact_changed", REASONS["fact_all_below"])
    (row,) = sent(svc)
    assert (row["reason"], row["case_id"]) == ("not_eligible", cid)
    (pending,) = pending_counsellor_escalations()
    assert pending.reason == "not_eligible" and pending.key == f"escalation:{cid}"
    assert SupportStore(svc.engine, "pai").get(cid).counsellor_status == "pending"


@pytest.mark.req("R-22")
def test_no_places_reason_is_a_route_problem_sent_by_its_event(svc):
    """A change that would leave no place (NO_PLACES_REASON) is not a system problem: the triggering event decides, so
    a fact change reaches the Counsellor as not_eligible and a rejection as all_rejected."""
    from app.os.replan.apply import NO_PLACES_REASON

    assert reason_for("student_fact_changed", NO_PLACES_REASON) == "not_eligible"
    assert reason_for("admission_rejected", NO_PLACES_REASON) == "all_rejected"
    escalate(svc, "student_fact_changed", NO_PLACES_REASON)
    (row,) = sent(svc)
    assert row["reason"] == "not_eligible"


@pytest.mark.req("R-22")
@pytest.mark.parametrize("key", ["unanswered_all", "unanswered_proposed"])
def test_unanswered_ladder_cases_stay_with_pai(svc, key):
    """P1-T8, Ruling problem 11: a request left unanswered calls a person at PAI, never the Counsellor, so the plan is
    not paused and the student is not sent back to choosing."""
    from app.os.requests import texts

    assert reason_for("document_missing", texts.text(key)) is None
    cid = escalate(svc, "document_missing", texts.text(key))
    assert sent(svc) == [] and pending_counsellor_escalations() == []  # nothing for the host's glue to deliver or act on
    case = SupportStore(svc.engine, "pai").get(cid)
    assert (case.status, case.counsellor_status) == ("open", None)
