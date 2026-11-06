"""P1-T6 Task 6 (R-08, row 6.16): a self-serve plan is adopted as the Counsellor's plan when the student agreed to it
and the Counsellor's decision is the same choice. The kernel changes the plan's identity in place (no rebuild, no task
change); intake does it only when four things hold (D-x6) and otherwise refuses with `self_serve_plan_open` as today.
Fictional students; the Germany playbook."""

import pytest
from sqlalchemy import func, insert, select, update

from app.os import models, ports
from app.os.adapters.counsellor import intake as intake_mod
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import PlanIdentityTaken, contract_sha256
from app.os.ports import plan_query, plan_source
from tests.os.test_counsellor_intake_v2 import NEW_PLACES, chosen, plan_row, run, svc  # noqa: F401 - fixture by name

pytestmark = pytest.mark.req("R-08")

P, T, R, A, EV = models.plans, models.tasks, models.plan_revisions, models.plan_adoptions, models.events
STUDENT = "ws-sample-1"  # the student of the v2 samples
SELF_REF = f"self:{STUDENT}:germany_master:winter:2027"
SAMPLE_PLACES = [{"programme_ref": "tu-chemnitz-embedded-systems", "rank": 1}, {"programme_ref": "ovgu-eeit", "rank": 2}]


def self_contract(places=None, **over) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": SELF_REF, "student_ref": STUDENT,
        "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027}, "programmes": places or SAMPLE_PLACES, **over})


@pytest.fixture
def world(svc, engine):  # noqa: F811
    """PAI OS on its ports with the Counsellor module on."""
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(svc)
    try:
        yield svc
    finally:
        ports.configure(None)


def self_plan(svc_, places=None) -> int:
    return svc_.plans.start_plan(self_contract(places)).plan_id


def agree(svc_, plan_id: int) -> str:
    assert plan_source.request_adoption(STUDENT, plan_id) == "recorded"
    return plan_row(svc_, plan_id).contract_sha256


def snapshot(svc_, plan_id: int) -> dict:
    with svc_.engine.connect() as conn:
        tasks = conn.execute(select(T.c.id, T.c.instance_key, T.c.state).where(T.c.plan_id == plan_id)
                             .order_by(T.c.id)).all()
        revisions = conn.execute(select(R.c.number, R.c.cause).where(R.c.plan_id == plan_id).order_by(R.c.number)).all()
        current = conn.execute(select(P.c.current_revision).where(P.c.id == plan_id)).scalar()
    return {"tasks": [tuple(t) for t in tasks], "revisions": [tuple(r) for r in revisions], "current": current}


def plans_count(svc_) -> int:
    with svc_.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(P)).scalar()


def adopted_at(svc_, plan_id: int):
    with svc_.engine.connect() as conn:
        return conn.execute(select(A.c.adopted_at).where(A.c.plan_id == plan_id)).scalar_one()


# --- the kernel ------------------------------------------------------------------------------------------------

def test_adopt_plan_keeps_tasks_and_revision(world):
    plan_id = self_plan(world)
    before = snapshot(world, plan_id)
    decision_contract = intake_mod._v1_contract(intake_mod.DecisionRecordV2.model_validate(chosen(1)))
    assert world.kernel.adopt_plan(plan_id, decision_contract.external_ref, decision_contract) is True
    assert snapshot(world, plan_id) == before  # tasks, task states, revisions and current_revision: unchanged
    row = plan_row(world, plan_id)
    assert row.source == "counsellor" and row.external_ref == "j-sample-1:DE:master"
    assert row.contract["source"] == "counsellor" and row.contract_sha256 == contract_sha256(decision_contract)
    with world.engine.connect() as conn:
        kinds = conn.execute(select(EV.c.type).where(EV.c.plan_id == plan_id, EV.c.type == "plan_adopted")).scalars().all()
    assert kinds == ["plan_adopted"]
    assert before["tasks"]  # the plan had steps of its own; all of them are in the snapshot


def test_adopt_plan_refuses_a_plan_that_is_not_open_self_serve(world):
    plan_id = self_plan(world)
    contract = intake_mod._v1_contract(intake_mod.DecisionRecordV2.model_validate(chosen(1)))
    assert world.kernel.adopt_plan(plan_id, contract.external_ref, contract) is True
    assert world.kernel.adopt_plan(plan_id, contract.external_ref, contract) is False  # already the Counsellor's
    other = world.plans.start_plan(self_contract(places=SAMPLE_PLACES[:1], student_ref="ws-other",
                                                 external_ref="self:ws-other:germany_master:winter:2027")).plan_id
    world.kernel.close_plan(other, "test")
    assert world.kernel.adopt_plan(other, "x:DE:master", contract) is False  # closed
    assert plan_row(world, other).source == "self_serve"


# --- the port ---------------------------------------------------------------------------------------------------

def test_request_adoption_port(world, engine):
    plan_id = self_plan(world)
    assert plan_source.request_adoption(STUDENT, plan_id) == "recorded"
    assert plan_source.request_adoption(STUDENT, plan_id) == "recorded"  # idempotent: one row
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(A)).scalar() == 1
    assert plan_source.request_adoption("ws-someone-else", plan_id) == "not_found"  # not the student's plan
    assert plan_source.request_adoption(STUDENT, plan_id + 999) == "not_found"
    with engine.begin() as conn:
        conn.execute(update(models.modules).values(enabled=False))
    assert plan_source.request_adoption(STUDENT, plan_id) == "module_off"


def test_self_serve_plan_query(world):
    assert plan_query.self_serve_plan(STUDENT) is None
    plan_id = self_plan(world)
    got = plan_query.self_serve_plan(STUDENT)
    assert got == {"plan_id": plan_id, "route_key": "germany_master", "origin": "PK", "destination": "DE",
                   "level": "master", "intake": {"term": "winter", "year": 2027}, "programmes": SAMPLE_PLACES,
                   "contract_sha256": plan_row(world, plan_id).contract_sha256}
    world.kernel.close_plan(plan_id, "test")
    assert plan_query.self_serve_plan(STUDENT) is None


# --- intake -----------------------------------------------------------------------------------------------------

def test_intake_adopts_with_intent_and_equal_choice(world):
    plan_id = self_plan(world)
    agree(world, plan_id)
    before = snapshot(world, plan_id)
    result = run(world, chosen(1))
    assert (result.status, result.plan_id) == ("revised", plan_id)
    IntakeStore(world.engine, "pai").finish(IntakeStore(world.engine, "pai").get("d-v1").id, result.status,
                                            result.reason, result.plan_id)
    assert plans_count(world) == 1  # no new plan row
    row = plan_row(world, plan_id)
    assert row.source == "counsellor" and row.external_ref == "j-sample-1:DE:master"
    assert snapshot(world, plan_id) == before  # the same steps, no task change, no revision
    assert adopted_at(world, plan_id) is not None
    assert [s.task_id for s in plan_query.plan_view(STUDENT).steps] == [t[0] for t in before["tasks"]]
    assert process(world, IntakeStore(world.engine, "pai").get("d-v1")).status == "revised"  # a repeat changes nothing
    assert snapshot(world, plan_id) == before and plans_count(world) == 1


def test_intake_refuses_without_intent(world):
    plan_id = self_plan(world)
    result = run(world, chosen(1))
    assert (result.status, result.reason, result.plan_id) == ("refused", "self_serve_plan_open", plan_id)
    assert plan_row(world, plan_id).source == "self_serve" and plans_count(world) == 1


def test_intake_refuses_when_the_choice_differs_from_the_plan(world):
    plan_id = self_plan(world)
    agree(world, plan_id)
    result = run(world, chosen(1, programmes=NEW_PLACES))  # the student agreed to another choice
    assert (result.status, result.reason) == ("refused", "self_serve_plan_open")
    assert plan_row(world, plan_id).source == "self_serve" and adopted_at(world, plan_id) is None


def test_intake_refuses_when_plan_changed_after_intent(world):
    plan_id = self_plan(world)
    agree(world, plan_id)
    world.plans.change_programmes(plan_id, lambda c: [p for p in c.programmes if p.programme_ref != "ovgu-eeit"]
                                  + [], "test:swap")  # the plan changes after the student agreed
    result = run(world, chosen(1, programmes=SAMPLE_PLACES[:1]))  # even a decision equal to the new plan
    assert (result.status, result.reason) == ("refused", "self_serve_plan_open")
    assert plan_row(world, plan_id).source == "self_serve" and adopted_at(world, plan_id) is None


def test_identity_taken_refuses_cleanly(world):
    plan_id = self_plan(world)
    agree(world, plan_id)
    taken = world.plans.start_plan(intake_mod._v1_contract(intake_mod.DecisionRecordV2.model_validate(
        chosen(1)))).plan_id  # a Counsellor plan with the identity the adoption would take ...
    world.kernel.close_plan(taken, "test")  # ... closed
    before = snapshot(world, plan_id)
    result = run(world, chosen(2))
    assert (result.status, result.reason, result.plan_id) == ("refused", "self_serve_plan_open", plan_id)
    row = plan_row(world, plan_id)
    assert row.source == "self_serve" and row.external_ref == SELF_REF  # untouched
    assert snapshot(world, plan_id) == before and adopted_at(world, plan_id) is None
    with world.engine.connect() as conn:  # uq_os_plans_identity holds: one row per (tenant, source, external_ref)
        counts = conn.execute(select(func.count()).select_from(P).group_by(P.c.tenant_id, P.c.source, P.c.external_ref)
                              ).scalars().all()
        assert counts == [1, 1] and conn.execute(select(func.count()).select_from(P).where(
            P.c.source == "counsellor", P.c.external_ref == "j-sample-1:DE:master")).scalar() == 1
    contract = intake_mod._v1_contract(intake_mod.DecisionRecordV2.model_validate(chosen(1)))
    with pytest.raises(PlanIdentityTaken):  # the kernel says so by itself too
        world.kernel.adopt_plan(plan_id, contract.external_ref, contract)
    assert plan_row(world, plan_id).source == "self_serve"


def test_adoption_without_consent_pauses_consent_missing(world):
    plan_id = self_plan(world)
    agree(world, plan_id)
    result = run(world, chosen(1, authorized_at=None))
    assert (result.status, result.reason, result.plan_id) == ("paused", "consent_missing", plan_id)
    row = plan_row(world, plan_id)
    assert row.source == "counsellor" and row.status == "paused" and adopted_at(world, plan_id) is not None
    again = run(world, chosen(2))  # the consent is back: the same plan resumes
    assert (again.status, again.plan_id) == ("revised", plan_id)
    assert plan_row(world, plan_id).status != "paused" and plans_count(world) == 1


def test_adoption_does_not_run_for_a_withdrawn_or_unsupported_decision(world):
    plan_id = self_plan(world)
    agree(world, plan_id)
    assert run(world, chosen(1, os_supported=False)).status == "unsupported"
    assert plan_row(world, plan_id).source == "self_serve"
