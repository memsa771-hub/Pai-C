"""Slice 8 Task 2: the EscalationSink port and the standalone adapter (spec §2.2, §2.5, S8-D12). Fictional data."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy import func, insert, select

from app.os import models, ports
from app.os.adapters.standalone.escalation import CompositeSink, StandaloneSink
from app.os.replan.store import SupportStore


def plan(engine, student: str = "stu-1") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source="self_serve", external_ref=f"pai-{student}", student_ref=student, contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


class FakeSink:
    def __init__(self, case_id: int) -> None:
        self.case_id, self.calls = case_id, []

    def escalate(self, plan_id, event_ids, reason, proposal_id=None) -> int:
        self.calls.append((plan_id, event_ids, reason, proposal_id))
        return self.case_id


@pytest.mark.standalone
def test_standalone_sink_opens_case(engine, clean):
    p = plan(engine)
    cid = StandaloneSink(engine, "pai").escalate(p, [4], "a step failed twice")
    got = SupportStore(engine, "pai").get(cid)
    assert (got.plan_id, got.student_ref, got.reason, got.event_ids, got.status) == (
        p, "stu-1", "a step failed twice", [4], "open")


def test_sink_reuses_case_for_event(engine, clean):
    p, sink = plan(engine), StandaloneSink(engine, "pai")
    first = sink.escalate(p, [4, 5], "fictional")
    assert sink.escalate(p, [4], "another reason") == first  # one case per triggering event, as in Slice 7
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.support_cases)).scalar() == 1
    assert sink.escalate(p, [], "no event") != first  # no event: always a new case


def test_composite_calls_each_returns_first():
    a, b = FakeSink(11), FakeSink(22)
    assert CompositeSink([a, b]).escalate(1, [2], "fictional", 3) == 11
    assert a.calls == b.calls == [(1, [2], "fictional", 3)]


def test_replanner_support_goes_through_sink(engine):
    from app.os.replan.apply import Replanner

    fake = FakeSink(7)
    plans = SimpleNamespace(kernel=SimpleNamespace(tenant_id="pai"))
    r = Replanner(engine, plans, {}, outbox=None, escalations=fake)
    assert r.support(3, [9], "No automatic change: fictional.", 5) == 7
    assert fake.calls == [(3, [9], "No automatic change: fictional.", 5)]


@pytest.mark.standalone
def test_services_escalate_through_standalone(engine, clean, os_db):
    from app.os.api.replan import replanner_for
    from app.os.api.services import make_services
    from app.os.settings import load_settings

    svc = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine)
    assert isinstance(svc.escalations, CompositeSink)
    assert replanner_for(svc).escalations is svc.escalations
    p = plan(engine)
    assert SupportStore(engine, "pai").get(svc.escalations.escalate(p, [1], "fictional")).plan_id == p


def test_ports_unavailable_when_not_mounted():
    from app.os.api.mount import mount_os

    ports.configure(None)
    with pytest.raises(ports.OsUnavailable):
        ports.services()
    assert mount_os(FastAPI(), env={"DATABASE_URL": "postgresql://x/y"}) is False  # OS off: still unavailable
    with pytest.raises(ports.OsUnavailable):
        ports.services()
    assert mount_os(FastAPI(), env={"OS_DATABASE_URL": "postgresql://unused/x", "OS_ENABLED": "true"}) is True
    assert ports.services().settings.os_enabled is True
    ports.configure(None)


@pytest.mark.req("R-11")
def test_pending_reads_stored_v1_rows(engine, clean):
    """A row written before T6 (EscalationV1) is read as v2 with no decision version."""
    from app.os.contracts.escalation import EscalationV1
    from app.os.contracts.escalation_v2 import EscalationV2
    from app.os.ports.escalation import pending_counsellor_escalations

    svc = SimpleNamespace(engine=engine, settings=SimpleNamespace(tenant_id="pai"))
    old = EscalationV1(key="escalation:3", case_id=3, journey_id="j-1", student_ref="ws-1", reason="blocking_gap",
                       note="Fixed note.", raised_at="2027-01-10T09:00:00+05:00").model_dump(mode="json", by_alias=True)
    new = EscalationV2(key="escalation:4", case_id=4, journey_id="j-1", student_ref="ws-1", decision_version=2,
                       reason="other", note="Fixed note.", raised_at="2027-01-10T09:00:00+05:00"
                       ).model_dump(mode="json", by_alias=True)
    with engine.begin() as conn:
        for p in (old, new):
            conn.execute(insert(models.outbox).values(tenant_id="pai", idempotency_key=p["key"], channel="counsellor",
                                                      recipient="ws-1", template="escalation", payload=p))
    ports.configure(svc)
    try:
        got = pending_counsellor_escalations()
    finally:
        ports.configure(None)
    assert [type(e) for e in got] == [EscalationV2, EscalationV2]
    assert [(e.key, e.decision_version) for e in got] == [("escalation:3", None), ("escalation:4", 2)]
