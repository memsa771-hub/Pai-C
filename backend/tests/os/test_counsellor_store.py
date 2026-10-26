"""Slice 8 Task 1: the Counsellor intake tables and module row (os_0013, spec §3). Fictional data."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.store import IntakeStore, SweepStore
from app.os.db import OS_SCHEMA

T0 = datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc)


def export(decision: str, student: str = "ws-1", chosen_at: datetime = T0, journey: str = "j-1") -> dict:
    """The parts of a fictional decision record export the store reads (the full export is Task 3's contract)."""
    return {"schema": "pai.decision_record.v1", "decision_id": decision, "journey_id": journey,
            "student_ref": student, "chosen_at": chosen_at.isoformat()}


def test_migration_up_down_up(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0012"], os_db)
    eng = create_engine(os_db)
    try:
        names = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        assert not names & {"os_counsellor_intake", "os_counsellor_sweep"}
        cols = {c["name"] for c in inspect(eng).get_columns("os_support_cases", schema=OS_SCHEMA)}
        assert not cols & {"counsellor_status", "counsellor_reason"}
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM os.os_modules WHERE module = 'counsellor'")).scalar() == 0
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(text("INSERT INTO os.os_plans (tenant_id, source, external_ref, student_ref, contract, "
                              "contract_sha256, status) VALUES ('pai', 'counsellor', 'x', 'ws-1', '{}', '0', 'closed')"))
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)
    eng = create_engine(os_db)
    try:
        with eng.connect() as conn:
            assert conn.execute(text("SELECT tenant_id, enabled FROM os.os_modules WHERE module = 'counsellor'")
                                ).one() == ("pai", False)  # inserted switched off (S8-D2)
    finally:
        eng.dispose()


def test_module_row_off_by_default(engine, clean):
    assert manifest.NAME == "counsellor" and manifest.TASK_TYPES == () and manifest.FALLBACK == "standalone"
    assert manifest.is_enabled(engine, "pai") is False  # no row at all: off
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=False))
    assert manifest.is_enabled(engine, "pai") is False
    with engine.begin() as conn:
        conn.execute(models.modules.update().where(models.modules.c.module == "counsellor").values(enabled=True))
    assert manifest.is_enabled(engine, "pai") is True
    assert manifest.is_enabled(engine, "other") is False


def test_closed_plan_status_allowed(engine, clean):
    with engine.begin() as conn:
        conn.execute(insert(models.plans).values(tenant_id="pai", source="counsellor", external_ref="j-1:DE:master",
                                                 student_ref="ws-1", contract={}, contract_sha256="0" * 64,
                                                 status="closed"))


def test_intake_duplicate_decision_ignored(engine, clean):
    store = IntakeStore(engine, "pai")
    assert store.add(export("d-1"), "a" * 64) is True
    assert store.add(export("d-1"), "b" * 64) is False  # the same decision again: the first copy stays (S8-D9)
    got = store.get("d-1")
    assert (got.student_ref, got.journey_id, got.chosen_at, got.export_sha256, got.status) == (
        "ws-1", "j-1", T0, "a" * 64, "pending")
    assert got.export == export("d-1") and got.reason is None and got.plan_id is None and got.processed_at is None
    assert store.get("d-2") is None


def test_pending_ordered_per_student(engine, clean):
    store = IntakeStore(engine, "pai")
    store.add(export("d-b2", "ws-b", T0 + timedelta(days=2)), "0" * 64)
    store.add(export("d-a1", "ws-a", T0 + timedelta(days=5)), "0" * 64)
    store.add(export("d-b1", "ws-b", T0), "0" * 64)
    store.add(export("d-a0", "ws-a", T0 + timedelta(days=1)), "0" * 64)
    assert [i.decision_id for i in store.pending()] == ["d-a0", "d-a1", "d-b1", "d-b2"]
    assert [i.decision_id for i in store.pending(limit=1)] == ["d-a0"]
    store.finish(store.get("d-a0").id, "refused", reason="not_authorized")
    got = store.get("d-a0")
    assert (got.status, got.reason) == ("refused", "not_authorized") and got.processed_at is not None
    assert [i.decision_id for i in store.pending()] == ["d-a1", "d-b1", "d-b2"]
    with pytest.raises(IntegrityError):
        store.finish(store.get("d-a1").id, "refused", reason="made_up")  # only the six refusal reasons (S8-D10)


def test_finish_records_plan_and_counsellor_status(engine, clean):
    store = IntakeStore(engine, "pai")
    store.add(export("d-1"), "0" * 64)
    with engine.begin() as conn:
        plan_id = conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref="j-1:DE:master", student_ref="ws-1", contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()
    store.finish(store.get("d-1").id, "planned", plan_id=plan_id)
    store.set_counsellor_status("d-1", "sent")
    got = store.get("d-1")
    assert (got.status, got.plan_id, got.counsellor_status) == ("planned", plan_id, "sent")


def test_support_case_counsellor_columns(engine, clean):
    with engine.begin() as conn:
        plan_id = conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref="j-1:DE:master", student_ref="ws-1", contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()
        C = models.support_cases
        conn.execute(insert(C).values(tenant_id="pai", plan_id=plan_id, student_ref="ws-1", reason="fictional",
                                      counsellor_status="pending", counsellor_reason="blocking_gap"))
        assert conn.execute(select(C.c.counsellor_status, C.c.counsellor_reason)).one() == ("pending", "blocking_gap")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(C).values(tenant_id="pai", plan_id=plan_id, student_ref="ws-1", reason="fictional",
                                      counsellor_reason="cost"))  # "cost" comes in a later version (S8-D12)


def test_sweep_mark_roundtrip(engine, clean):
    store = SweepStore(engine, "pai")
    assert store.mark() is None
    store.set_mark({"chosen_at": T0.isoformat(), "decision_id": "d-1"})
    store.set_mark({"chosen_at": (T0 + timedelta(hours=1)).isoformat(), "decision_id": "d-2"})
    assert store.mark() == {"chosen_at": (T0 + timedelta(hours=1)).isoformat(), "decision_id": "d-2"}


def test_tenant_isolation(engine, clean):
    IntakeStore(engine, "pai").add(export("d-1"), "0" * 64)
    SweepStore(engine, "pai").set_mark({"decision_id": "d-1"})
    other = IntakeStore(engine, "other")
    assert other.get("d-1") is None and other.pending() == []
    assert other.add(export("d-1"), "0" * 64) is True  # the decision is unique per tenant
    assert SweepStore(engine, "other").mark() is None
