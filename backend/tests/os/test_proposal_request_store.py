"""P1-T6 Task 1: the proposal store's `requested` state (R-07, D-x1, D-x3). Fictional data."""

import pytest
from sqlalchemy import insert

from app.os import models
from app.os.replan.store import ProposalStore

pytestmark = pytest.mark.req("R-07")


def plan(engine, student: str = "stu-1") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref=f"j-{student}:XX:master", student_ref=student,
            contract={}, contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def make(engine, base_version: int | None = 3, student: str = "stu-1") -> tuple[ProposalStore, int]:
    store = ProposalStore(engine, "pai")
    pid = store.create(plan(engine, student), [1], "rules", [], [], big=True, expires_at=None, base_decision_version=base_version)
    return store, pid


def test_create_keeps_the_base_decision_version(engine, clean):
    store, pid = make(engine)
    got = store.get(pid)
    assert (got.base_decision_version, got.requested_version, got.request_outcome) == (3, None, None)
    assert make(engine, None, "stu-2")[0].get(pid + 1).base_decision_version is None  # a proposal made before os_0021


def test_request_sets_status_on_callers_connection(engine, clean):
    store, pid = make(engine)
    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            assert store.request(conn, pid, 5) is True
            raise RuntimeError("roll back")
    got = store.get(pid)
    assert (got.status, got.revision) == ("pending", None)  # nothing committed: the caller's transaction decides
    with engine.begin() as conn:
        assert store.request(conn, pid, 5) is True
        assert store.request(conn, pid, 5) is False  # only a pending proposal can be requested
    got = store.get(pid)
    assert (got.status, got.revision) == ("requested", 5) and got.answered_at is not None
    assert store.pending_for("stu-1") == []


def test_settle_requested_only_moves_requested(engine, clean):
    store, pid = make(engine)
    assert store.settle_requested(store.get(pid).plan_id, 9, 2) == 0  # pending stays pending
    with engine.begin() as conn:
        store.request(conn, pid, None)
    assert store.set_requested_version(pid, 4, "written") is True
    plan_id = store.get(pid).plan_id
    assert store.settle_requested(plan_id, 3, 2) == 0  # version 3 is applied, 4 is not yet
    assert store.get(pid).status == "requested"
    assert store.settle_requested(plan_id, 4, 2) == 1
    got = store.get(pid)
    assert (got.status, got.revision, got.requested_version, got.request_outcome) == ("accepted", 2, 4, "written")
    assert store.settle_requested(plan_id, 4, 2) == 0  # a second call changes nothing


def test_settle_keeps_an_earlier_revision_when_none_is_given(engine, clean):
    store, pid = make(engine)
    with engine.begin() as conn:
        store.request(conn, pid, 6)
    store.set_requested_version(pid, 4, "duplicate")
    assert store.settle_requested(store.get(pid).plan_id, 5, None) == 1
    assert store.get(pid).revision == 6


def test_settle_keeps_the_revision_the_other_ops_made(engine, clean):
    store, pid = make(engine)
    with engine.begin() as conn:
        store.request(conn, pid, 6)
    store.set_requested_version(pid, 4, "written")
    assert store.settle_requested(store.get(pid).plan_id, 5, 9) == 1
    assert store.get(pid).revision == 6  # the earlier value wins


def test_expire_requested_records_outcome(engine, clean):
    store, pid = make(engine)
    assert store.expire_requested(pid, "stale") is False  # still pending: not its to expire
    with engine.begin() as conn:
        store.request(conn, pid, None)
    assert store.expire_requested(pid, "stale") is True
    got = store.get(pid)
    assert (got.status, got.request_outcome) == ("expired", "stale") and got.answered_at is not None
    assert store.expire_requested(pid, "refused") is False
    assert store.get(pid).request_outcome == "stale"


def test_set_requested_version_only_while_requested(engine, clean):
    store, pid = make(engine)
    assert store.set_requested_version(pid, 4, "written") is False
    with pytest.raises(ValueError):
        store.set_requested_version(pid, 4, "stale")  # stale and refused expire the proposal instead


def test_set_status_stamps_answered_at_for_requested(engine, clean):
    store, pid = make(engine)
    store.set_status(pid, "requested", revision=1)
    assert store.get(pid).answered_at is not None
