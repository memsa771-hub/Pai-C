"""Slice 8 final review: the fix pass (PAI OS side). One test per Important finding, each failing before its fix.
Fictional data."""

import pytest
from sqlalchemy import insert, select

from app.os import models
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.queries import student_programmes
from app.os.api.replan import changes_paused
from app.os.api.self_serve import student_plan
from app.os.kernel import IllegalTransition
from app.os.replan.run import HANDOVER_PREFIX
from app.os.replan.store import ProposalStore
from tests.os.test_counsellor_escalation import event, plan, sent
from tests.os.test_counsellor_escalation import svc as esc_svc  # noqa: F401  (fixture)
from tests.os.test_counsellor_intake import run, sample
from tests.os.test_counsellor_intake import svc  # noqa: F401  (fixture)

P, PR = models.plans, models.proposals


# --- I1: with no Supervisor, a route problem still reaches the Counsellor (spec §2.5: by the triggering event) ---

@pytest.mark.parametrize("type_,handover,expected", [
    ("route_invalid", "no rule for 'route_invalid'", "not_eligible"),
    ("admission_rejected", "a rejection left 0 programme(s) and there is no close match", "all_rejected"),
    ("deadline_at_risk", "a deadline of programme 'p1' is at risk and no student step blocks it", "deadline_passed"),
    ("escalate", "no rule for 'escalate'", "blocking_gap"),
])
def test_i1_handover_without_supervisor_reaches_counsellor(esc_svc, type_, handover, expected):  # noqa: F811
    p = plan(esc_svc)
    esc_svc.escalations.escalate(p, [event(esc_svc, p, type_)], f"{HANDOVER_PREFIX}{handover}.")
    (row,) = sent(esc_svc)
    assert row["reason"] == expected and "rule" not in row["note"]  # the fixed note, never the hand-over text


# --- I2: a closed plan stays closed ---

def _closed(svc):  # noqa: F811
    old = run(svc, sample("export_valid_de.json")).plan_id
    with svc.engine.begin() as conn:
        conn.execute(insert(PR).values(tenant_id="pai", plan_id=old, source="rules", status="pending", big=True))
    run(svc, sample("export_new_country.json"))
    return old


def test_i2_close_plan_expires_pending_proposals(svc):  # noqa: F811
    old = _closed(svc)
    with svc.engine.connect() as conn:
        assert conn.execute(select(PR.c.status).where(PR.c.plan_id == old)).scalars().all() == ["expired"]
    assert ProposalStore(svc.engine, "pai").pending_for("ws-sample-1") == []


def test_i2_closed_plan_refuses_revision(svc):  # noqa: F811
    old = _closed(svc)
    contract, sha = svc.plans._contract(old)
    draft = svc.plans.compile(contract, svc.plans._pinned(old), old)
    with pytest.raises(IllegalTransition, match="closed"):
        svc.kernel.revise(old, "replan:1", draft, based_on=sha)
    with svc.engine.connect() as conn:
        assert conn.execute(select(P.c.status).where(P.c.id == old)).scalar_one() == "closed"


def test_i2_closed_plans_are_not_live(svc):  # noqa: F811
    old = _closed(svc)
    with svc.engine.begin() as conn:
        conn.execute(P.update().where(P.c.id == old).values(changes_paused=True))
        new = conn.execute(select(P.c.id).where(P.c.status != "closed")).scalar_one()
        conn.execute(P.update().where(P.c.id == new).values(status="done"))
    refs = {p["programme_ref"] for p in student_programmes(svc.engine, "pai", "ws-sample-1")}
    assert not refs & {"tu-chemnitz-embedded-systems", "ovgu-eeit"}  # the closed plan's places are gone
    assert changes_paused(svc, "ws-sample-1") is False
    assert student_plan(svc.plans, "ws-sample-1") is None  # only a done and a closed plan: no open plan


# --- I3: an outdated refused decision is not sent to the Counsellor ---

def test_i3_outdated_refusal_not_escalated(svc):  # noqa: F811
    store = IntakeStore(svc.engine, "pai")
    newer = sample("export_valid_de.json", decision_id="d-newer", chosen_at="2027-01-30T09:00:00+05:00")
    store.add(newer, "0" * 64)  # a newer decision for the same journey is already in
    r = run(svc, sample("export_unknown_programme.json"))
    assert (r.status, r.reason) == ("refused", "unknown_programme")
    assert store.get("d-sample-5").counsellor_status is None
    with svc.engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.id).where(models.outbox.c.channel == "counsellor")).all() == []
    lone = run(svc, sample("export_pk_pk.json", decision_id="d-latest", chosen_at="2027-02-05T09:00:00+05:00"))
    assert lone.reason == "route_not_supported" and store.get("d-latest").counsellor_status == "pending"


def test_i3_module_on_port(svc):  # noqa: F811
    from app.os import ports
    from app.os.ports.plan_source import counsellor_enabled

    ports.configure(svc)
    try:
        assert counsellor_enabled() is False
        with svc.engine.begin() as conn:
            conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
        assert counsellor_enabled() is True
    finally:
        ports.configure(None)
