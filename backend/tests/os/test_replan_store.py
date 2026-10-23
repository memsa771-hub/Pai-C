"""Slice 7 Task 1: replan tables (os_0012) and stores (spec §3). Fictional data."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, insert, inspect

from app.os import models
from app.os.db import OS_SCHEMA
from app.os.replan.store import OverrideStore, ProposalStore, SupportStore

LATER = datetime(2027, 3, 8, tzinfo=timezone.utc)


def plan(engine, tenant: str = "pai", student: str = "stu-1") -> int:
    """A bare plan row (the tests' own write; the kernel writes plans in the app)."""
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id=tenant, source="self_serve", external_ref=f"{tenant}-{student}", student_ref=student,
            contract={}, contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def test_migration_up_down_up(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0011"], os_db)
    eng = create_engine(os_db)
    try:
        names = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        assert not names & {"os_proposals", "os_plan_overrides", "os_support_cases"}
        assert "changes_paused" not in {c["name"] for c in inspect(eng).get_columns("os_plans", schema=OS_SCHEMA)}
        assert "plan_id" not in {c["name"] for c in inspect(eng).get_columns("os_agent_runs", schema=OS_SCHEMA)}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_proposal_store_roundtrip(engine, clean):
    p, store = plan(engine), ProposalStore(engine, "pai")
    ops = [{"op": "cancel_programme", "programme_ref": "p1", "reason": "fictional"}]
    pid = store.create(p, [7], "rules", ops, [], big=True, expires_at=LATER, based_on="a" * 64, base_revision=4)
    got = store.get(pid)
    assert (got.based_on, got.base_revision) == ("a" * 64, 4)  # the plan it was made against (final review I4)
    assert (got.plan_id, got.event_ids, got.source, got.ops, got.big, got.status) == (p, [7], "rules", ops, True,
                                                                                       "pending")
    assert store.for_event(7).id == pid and store.for_event(8) is None
    assert [x.id for x in store.pending_for("stu-1")] == [pid] and store.pending_for("stu-2") == []
    store.set_status(pid, "accepted", revision=3)
    got = store.get(pid)
    assert (got.status, got.revision) == ("accepted", 3) and got.answered_at is not None
    assert store.pending_for("stu-1") == []


def test_override_store_active_only(engine, clean):
    p, store = plan(engine), OverrideStore(engine, "pai")
    pid = ProposalStore(engine, "pai").create(p, [1], "rules", [], [], big=False, expires_at=None)
    store.add(p, pid, "skip", "ielts_book", {})
    store.add(p, pid, "add", "review_visa_file", {"programme_ref": None})
    assert [(o.op, o.target) for o in store.active(p)] == [("skip", "ielts_book"), ("add", "review_visa_file")]
    store.deactivate(pid)
    assert store.active(p) == []


def test_support_open_resolve(engine, clean):
    p, store = plan(engine), SupportStore(engine, "pai")
    cid = store.open(p, "stu-1", "a step failed twice", [4])
    assert [c.id for c in store.list("open")] == [cid] and store.get(cid).status == "open"
    assert store.resolve(cid, "retried by hand") == p
    got = store.get(cid)
    assert (got.status, got.resolution) == ("resolved", "retried by hand") and got.resolved_at is not None
    assert store.list("open") == [] and [c.id for c in store.list()] == [cid]


def test_tenant_isolation(engine, clean):
    p = plan(engine)
    pid = ProposalStore(engine, "pai").create(p, [1], "rules", [], [], big=True,
                                              expires_at=LATER + timedelta(days=1))
    cid = SupportStore(engine, "pai").open(p, "stu-1", "fictional", [1])
    assert ProposalStore(engine, "other").get(pid) is None and ProposalStore(engine, "other").pending_for("stu-1") == []
    assert SupportStore(engine, "other").get(cid) is None and SupportStore(engine, "other").list() == []
    assert OverrideStore(engine, "other").active(p) == []
