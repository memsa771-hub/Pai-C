"""P1-T10 A1: the read-only OS view for the consistency check (R-05). The Germany playbook and the fake routes;
fictional students."""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, update

from app.os import clock, models, ports
from app.os.adapters.counsellor.store import IntakeStore
from app.os.consistency import view
from app.os.consistency.store import ConsistencyStore
from app.os.kernel.kernel import contract_sha256
from app.os.ports import consistency as port
from app.os.ports import escalation, plan_query, plan_source
from app.os.replan import events as replan_events
from tests.os.test_counsellor_intake_v2 import NEW_PLACES, chosen, run, svc, v2, withdrawn  # noqa: F401

pytestmark = pytest.mark.req("R-05")
TENANT = "pai"


def apply(svc, export: dict):
    """Stores and processes the export, and finishes the intake row as the worker does."""
    store = IntakeStore(svc.engine, TENANT)
    result = run(svc, export)
    store.finish(store.get(export["decision_id"]).id, result.status, result.reason, result.plan_id)
    return result


def side(svc, export=None, student="ws-sample-1"):
    return view.os_side(svc.engine, TENANT, student, export)


def test_view_holds_codes_ids_and_hashes_only():
    for cls in (view.OsSide, view.PlanView, view.FactEventView):
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen
    names = {f.name for c in (view.OsSide, view.PlanView, view.FactEventView) for f in dataclasses.fields(c)}
    assert not names & {"value", "values", "text", "title", "filename", "name", "contract", "export", "payload"}
    # every field is a number, a bool, a short code or hash, or a collection of those
    for c in (view.OsSide, view.PlanView, view.FactEventView):
        for f in dataclasses.fields(c):
            assert "dict" not in str(f.type) and "bytes" not in str(f.type), f.name


def test_contract_matches_the_export_after_a_revision(svc):
    apply(svc, chosen(1))
    second = chosen(2, programmes=NEW_PLACES)
    assert apply(svc, second).status == "revised"
    got = side(svc, second)
    (plan,) = got.plans
    assert plan.contract_matches_export is True
    assert got.latest_version == 2 and got.intake_status_by_version == {1: "planned", 2: "revised"}
    assert plan.decision_version == 2 and plan.status in ("active", "at_risk")
    assert plan.export_hash_matches is False  # the test stored a placeholder hash, not the export's own
    with svc.engine.begin() as conn:
        conn.execute(update(models.counsellor_intake).where(models.counsellor_intake.c.decision_id == "d-v2")
                     .values(export_sha256=plan_source.export_sha256(second)))
    assert side(svc, second).plans[0].export_hash_matches is True


def test_a_changed_contract_does_not_match(svc):
    first = chosen(1)
    result = apply(svc, first)
    assert side(svc, first).plans[0].contract_matches_export is True
    with svc.engine.begin() as conn:  # a hand edit of the stored contract
        row = conn.execute(select(models.plans.c.contract).where(models.plans.c.id == result.plan_id)).scalar_one()
        row["programmes"] = row["programmes"][:1]
        conn.execute(update(models.plans).where(models.plans.c.id == result.plan_id).values(
            contract=row, contract_sha256="f" * 64))
    assert side(svc, first).plans[0].contract_matches_export is False
    assert side(svc, None).plans[0].contract_matches_export is None  # no export given: not known


def test_a_withdrawn_plan_shows_status_closed(svc):
    apply(svc, chosen(1))
    gone = withdrawn(2)
    apply(svc, gone)
    got = side(svc, gone)
    (plan,) = got.plans
    assert (plan.status, plan.close_reason) == ("closed", "withdrawn")
    assert plan.contract_matches_export is None  # a withdrawn export is not a chosen one
    assert got.intake_status_by_version[2] == "withdrawn"


def test_refusal_and_pending_rows_are_visible_with_their_age(svc):
    store = IntakeStore(svc.engine, TENANT)
    store.add(chosen(1, programmes=[{"programme_ref": "nowhere", "rank": 1}]), "0" * 64)
    got = side(svc)
    assert got.intake_status_by_version == {1: "pending"} and got.latest_version == 1
    assert abs((clock.now() - got.intake_pending_since_by_version[1]).total_seconds()) < 60
    store.finish(store.get("d-v1").id, "refused", "unknown_programme", None)
    assert side(svc).refusal_by_version == {1: "unknown_programme"}
    assert side(svc).intake_pending_since_by_version == {}  # no longer pending


def test_the_vault_version_and_unprocessed_fact_events(svc):
    first = chosen(1)
    result = apply(svc, first)
    with svc.engine.begin() as conn:
        conn.execute(insert(models.vault_events).values(
            tenant_id=TENANT, student_ref="ws-sample-1", vault_version=4, keys=["education.matric.marks_obtained"],
            event={}, occurred_at=clock.now()))
        replan_events.record(conn, TENANT, result.plan_id, "student_fact_changed",
                             {"keys": ["education.matric.marks_obtained"], "vault_version": 4}, "4")
    got = side(svc, first)
    assert got.latest_vault_version == 4
    assert [(e.plan_id, e.vault_version) for e in got.unprocessed_fact_events] == [(result.plan_id, 4)]
    assert got.unprocessed_fact_events[0].age_seconds >= 0 and got.unprocessed_fact_events[0].at.tzinfo
    assert side(svc, first, "someone-else").unprocessed_fact_events == ()


def test_needed_file_refs_and_duplicate_requests(svc):
    first = chosen(1)
    result = apply(svc, first)
    with svc.engine.begin() as conn:
        for n, status in enumerate(("confirmed", "deleted")):
            conn.execute(insert(models.documents).values(
                tenant_id=TENANT, student_ref="ws-sample-1", doc_type="transcript", type_version=1, filename="a.pdf",
                content_type="application/pdf", size=1, sha256=f"{n}" * 64, status=status, file_ref=f"file-{n}"))
    got = side(svc, first)
    assert got.needed_file_refs == ("file-0",)  # a deleted document needs nothing
    assert got.duplicate_requests == ()
    assert result.plan_id


def test_counsellor_students_lists_plans_and_intakes(svc):
    apply(svc, chosen(1))
    IntakeStore(svc.engine, TENANT).add({**chosen(1), "decision_id": "d-x", "student_ref": "ws-two"}, "0" * 64)
    with svc.engine.begin() as conn:  # a self-serve plan is not a Counsellor student
        conn.execute(insert(models.plans).values(
            tenant_id=TENANT, source="self_serve", external_ref="pai-ws-three", student_ref="ws-three", contract={},
            contract_sha256="0" * 64))
    assert view.counsellor_students(svc.engine, TENANT) == ["ws-sample-1", "ws-two"]


def test_cases_never_set_support_case_open_on_the_summary(svc):
    result = apply(svc, chosen(1))
    ConsistencyStore(svc.engine, TENANT).open_or_touch("ws-sample-1", 2, result.plan_id, ["contract_hash"])
    ports.configure(svc)
    try:
        assert plan_query.plan_summary("ws-sample-1").support_case_open is False
        assert escalation.pending_counsellor_escalations() == []
    finally:
        ports.configure(None)


def test_the_port_reads_and_writes_through_services(svc):
    first = chosen(1)
    apply(svc, first)
    with pytest.raises(ports.OsUnavailable):
        port.students()
    ports.configure(svc)
    try:
        assert port.students() == ["ws-sample-1"]
        assert port.side("ws-sample-1", first).latest_version == 1
        case, created = port.open_case("ws-sample-1", 1, None, ["no_plan"])
        assert created and [c.id for c in port.cases("open")] == [case]
        run_id = port.claim_run(datetime(2027, 1, 20).date(), "nightly")
        assert run_id is not None and port.claim_run(datetime(2027, 1, 20).date(), "nightly") is None
        port.finish_run(run_id, {"1": 1})
        assert port.resolve(case, "ok") is True and port.cases("open") == []
    finally:
        ports.configure(None)
