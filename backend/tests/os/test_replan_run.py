"""Slice 7 Task 7: the os.replan workflow, limits, proposals and support cases (spec S7-D5..D10, D12). DBOS in this
process; the Supervisor is a FunctionModel. Fictional data."""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select, update

from app.os import models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.replan import events
from app.os.replan.apply import ProposalStale, Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.run import enqueue_replan, register_replan, replan_workflow_id
from app.os.replan.store import ProposalStore, SupportStore
from app.os.replan.supervisor import build_supervisor
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT

TENANT, STUDENT = "pai", TEST_STUDENT.student_ref
P1 = "tu-chemnitz-embedded-systems"
SPEC = load_agent_spec(AGENT_DIR / "supervisor.v1.yaml")
NOW = datetime(2027, 2, 1, 9, tzinfo=timezone.utc)
T, REV = models.tasks, models.plan_revisions
SUPERVISOR_OPS = {"ops": [{"op": "request_from_student", "instance_key": "travel_insurance",
                           "message": "Please buy your insurance.", "reason": "The visa needs it."}],
                  "summary": "Ask for the insurance."}


def fake_model(args):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])
    return FunctionModel(fn)


class Ctx:
    def __init__(self, engine, client, replanner, plan_id):
        self.engine, self.client, self.r, self.plan_id = engine, client, replanner, plan_id

    def event(self, type_, dedupe="k1", **payload) -> int:
        with self.engine.begin() as conn:
            return events.record(conn, TENANT, self.plan_id, type_, payload, dedupe)

    def run(self, event_id: int, generation: int = 0) -> dict:
        wid = enqueue_replan(self.client, TENANT, self.plan_id, event_id, generation)
        return self.client.retrieve_workflow(wid).get_result()

    def causes(self) -> list[str]:
        with self.engine.connect() as conn:
            return conn.execute(select(REV.c.cause).where(REV.c.plan_id == self.plan_id).order_by(REV.c.number)) \
                .scalars().all()


def make(os_db, engine, supervisor=True):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
                              "OS_PRICE_STRONG_IN": "2.5", "OS_PRICE_STRONG_CACHED": "0.25",
                              "OS_PRICE_STRONG_OUT": "15"})
    kb = SqlKnowledge(engine, TENANT)
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    kernel = Kernel(engine, TENANT, clock=lambda: NOW)
    plans = PlanService(engine, settings, kernel, kb, load_playbook_dir(), today=lambda: NOW.date())
    replanner = Replanner(engine, plans, load_replan_configs(), Outbox(engine, TENANT), clock=lambda: NOW)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), kernel)
    sup = (build_supervisor(fake_model(SUPERVISOR_OPS), SPEC), SPEC) if supervisor else None
    register_replan(engine, settings, replanner, sup)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    return Ctx(engine, client, replanner, plans.start_plan(TEST_STUDENT).plan_id), client


@pytest.fixture
def ctx(os_db, engine, clean):
    from dbos import DBOS

    c, client = make(os_db, engine)
    try:
        yield c
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


@pytest.fixture
def bare(os_db, engine, clean):
    from dbos import DBOS

    c, client = make(os_db, engine, supervisor=False)
    try:
        yield c
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def test_rejection_proposes_then_accept_cancels(ctx):
    got = ctx.run(ctx.event("admission_rejected", programme_ref=P1))
    assert got["status"] == "pending"
    p = ProposalStore(ctx.engine, TENANT).get(got["proposal_id"])
    assert p.big and p.source == "rules" and p.ops[0]["op"] == "cancel_programme"
    assert NOW < p.expires_at <= NOW + timedelta(days=7)
    assert not [c for c in ctx.causes() if c.startswith("replan:")]  # nothing changes before the student says yes
    ctx.r.accept(STUDENT, p.id)
    assert ctx.causes()[-1] == f"replan:{p.id}"
    with ctx.engine.connect() as conn:
        live = conn.execute(select(T.c.instance_key).where(T.c.plan_id == ctx.plan_id, T.c.programme_ref == P1,
                                                           T.c.state != "cancelled")).all()
    assert live == [] and ProposalStore(ctx.engine, TENANT).get(p.id).status == "accepted"


def test_decline_changes_nothing(ctx):
    pid = ctx.run(ctx.event("admission_rejected", programme_ref=P1))["proposal_id"]
    before = ctx.causes()
    ctx.r.decline(STUDENT, pid)
    assert ProposalStore(ctx.engine, TENANT).get(pid).status == "declined" and ctx.causes() == before
    with pytest.raises(ProposalStale):
        ctx.r.accept(STUDENT, pid)


def test_small_change_applies_at_once(ctx):
    got = ctx.run(ctx.event("document_missing", instance_key="travel_insurance"))
    assert got["status"] == "applied"
    with ctx.engine.connect() as conn:
        keys = conn.execute(select(models.outbox.c.idempotency_key)).scalars().all()
    assert f"replan:{ctx.plan_id}:travel_insurance:{NOW.date().isoformat()}" in keys  # one nudge per step per day


def test_override_change_is_a_replan_revision(ctx):
    got = ctx.run(ctx.event("approved_changed", template_key="review_visa_file", programme_ref=None))
    assert got["status"] == "applied" and ctx.causes()[-1] == f"replan:{got['proposal_id']}"
    with ctx.engine.connect() as conn:
        assert conn.execute(select(T.c.id).where(T.c.plan_id == ctx.plan_id,
                                                 T.c.instance_key == "review_visa_file#2")).first() is not None


def test_handover_with_fake_supervisor(ctx):
    got = ctx.run(ctx.event("escalate", instance_key="travel_insurance"))
    p = ProposalStore(ctx.engine, TENANT).get(got["proposal_id"])
    assert got["status"] == "applied" and p.source == "supervisor" and p.ops[0]["op"] == "request_from_student"
    with ctx.engine.connect() as conn:
        runs = conn.execute(select(models.agent_runs.c.agent).where(
            models.agent_runs.c.plan_id == ctx.plan_id)).scalars().all()
    assert runs == ["supervisor"]


def test_no_supervisor_opens_support_case(bare):
    eid = bare.event("escalate", instance_key="travel_insurance")
    assert bare.run(eid)["status"] == "support"
    [case] = SupportStore(bare.engine, TENANT).list("open")
    assert case.plan_id == bare.plan_id and case.event_ids == [eid]
    assert events.pending(bare.engine, TENANT) == []


def test_retry_then_close(ctx):
    task_id = ctx.engine.connect().execute(select(T.c.id).where(
        T.c.plan_id == ctx.plan_id, T.c.instance_key == "applications_submitted")).scalar_one()
    with ctx.engine.begin() as conn:
        conn.execute(update(T).where(T.c.id == task_id).values(state="failed", attempt=1))
    got = ctx.run(ctx.event("task_failed", instance_key="applications_submitted", attempt=1))
    assert got["status"] == "retried"
    with ctx.engine.connect() as conn:
        assert conn.execute(select(T.c.state).where(T.c.id == task_id)).scalar_one() != "failed"
    assert events.pending(ctx.engine, TENANT) == []


def test_same_event_once(ctx):
    """Review Focus #2: the same event twice (and a replay) gives one proposal and one revision."""
    eid = ctx.event("approved_changed", template_key="review_visa_file", programme_ref=None)
    first = ctx.run(eid)
    assert ctx.run(eid) == first
    wid = replan_workflow_id(TENANT, ctx.plan_id, eid, 0)
    forked = ctx.client.fork_workflow(wid, 1)
    ctx.client.retrieve_workflow(forked.workflow_id).get_result()
    assert len(ProposalStore(ctx.engine, TENANT).for_plan(ctx.plan_id)) == 1
    assert sum(c.startswith("replan:") for c in ctx.causes()) == 1


def test_limit_counts_replan_only_and_pause_holds(ctx):
    """Review Focus #5: the daily limit counts replan revisions only; a paused plan does not change."""
    with ctx.engine.begin() as conn:  # earlier today (the kernel's writes, simulated): 3 replans and a swap
        n = conn.execute(select(models.plans.c.current_revision).where(models.plans.c.id == ctx.plan_id)).scalar()
        for i, cause in enumerate(["replan:90", "programmes:swap:a->b", "replan:91", "replan:92"], n + 1):
            conn.execute(REV.insert().values(tenant_id=TENANT, plan_id=ctx.plan_id, number=i, cause=cause, diff={},
                                             created_at=NOW - timedelta(hours=1)))
        conn.execute(update(models.plans).where(models.plans.c.id == ctx.plan_id).values(current_revision=n + 4))
    got = ctx.run(ctx.event("approved_changed", template_key="review_visa_file", programme_ref=None))
    assert got["status"] == "paused"
    assert ctx.r.plans.kernel.changes_paused(ctx.plan_id)
    assert [c.reason for c in SupportStore(ctx.engine, TENANT).list("open")] == [
        "Changes are paused: this plan reached today's limit of 3 automatic changes."]
    later = ctx.event("document_missing", dedupe="k2", instance_key="travel_insurance")
    assert ctx.run(later)["status"] == "paused"
    assert later in [e.id for e in events.pending(ctx.engine, TENANT)]  # kept for after the case is resolved


def test_expire_due(ctx):
    pid = ctx.run(ctx.event("admission_rejected", programme_ref=P1))["proposal_id"]
    assert ctx.r.expire_due(NOW) == 0
    assert ctx.r.expire_due(NOW + timedelta(days=8)) == 1
    assert ProposalStore(ctx.engine, TENANT).get(pid).status == "expired"
    with pytest.raises(ProposalStale):
        ctx.r.accept(STUDENT, pid)


def test_accept_refused_when_plan_changed(ctx):
    """Review Focus #3 (core): accepting after the plan moved on re-checks and refuses."""
    pid = ctx.run(ctx.event("admission_rejected", programme_ref=P1))["proposal_id"]
    keep = lambda c: [p.model_copy(update={"rank": i}) for i, p in  # noqa: E731
                      enumerate((p for p in c.programmes if p.programme_ref != P1), 1)]
    ctx.r.plans.change_programmes(ctx.plan_id, keep, "programmes:remove")  # the student removed it themselves
    with pytest.raises(ProposalStale):
        ctx.r.accept(STUDENT, pid)


def test_accept_other_student_refused(ctx):
    pid = ctx.run(ctx.event("admission_rejected", programme_ref=P1))["proposal_id"]
    with pytest.raises(PermissionError):
        ctx.r.accept("stu-other", pid)


def test_today_is_fixed(ctx):
    assert ctx.r.clock() == NOW and date(2027, 2, 1) == NOW.date()


# --- final review fixes ---------------------------------------------------------------------------------------


def test_uncompilable_plan_opens_support_case(ctx, monkeypatch):
    """Final review C1: a plan that no longer compiles reaches a person; the workflow never fails."""
    from app.os.compiler import CompileError

    def broken(*a, **k):
        raise CompileError("cycle: a -> b -> a")

    monkeypatch.setattr(ctx.r.plans, "compile", broken)
    eid = ctx.event("document_missing", instance_key="travel_insurance")
    assert ctx.run(eid)["status"] == "support"
    assert [c.event_ids for c in SupportStore(ctx.engine, TENANT).list("open")] == [[eid]]
    assert events.pending(ctx.engine, TENANT) == []


def test_decide_and_accept_wait_for_the_plan_lock(ctx):
    """Final review I2, I5: one plan's replans and answers run one at a time."""
    import threading

    eid = ctx.event("document_missing", instance_key="travel_insurance")
    from app.os.replan.ops import RequestFromStudent

    op = RequestFromStudent(instance_key="travel_insurance", message="Please.", reason="On time.")
    done = threading.Event()
    with ctx.r.plan_lock(ctx.plan_id):
        t = threading.Thread(target=lambda: (ctx.r.decide(ctx.plan_id, [eid], "rules", [op]), done.set()))
        t.start()
        assert not done.wait(1.0)  # blocked while the lock is held
    t.join(30)
    assert done.is_set()


def test_one_nudge_per_step_per_day(ctx):
    """Final review I2: two requests for the same step on one day send one message."""
    from app.os.replan.ops import RequestFromStudent

    op = RequestFromStudent(instance_key="travel_insurance", message="Please.", reason="On time.")
    for n in (1, 2):
        ctx.r.decide(ctx.plan_id, [ctx.event("document_missing", dedupe=f"n{n}", instance_key="travel_insurance")],
                     "rules", [op])
    with ctx.engine.connect() as conn:
        keys = [k for k in conn.execute(select(models.outbox.c.idempotency_key)).scalars() if k.startswith("replan:")]
    assert len(keys) == 1


def test_failed_apply_leaves_no_override(ctx, monkeypatch):
    """Final review I3: if the revision cannot be written, no override stays behind to apply later."""
    from app.os.kernel import StaleDraft

    pid = ctx.run(ctx.event("admission_rejected", programme_ref=P1))["proposal_id"]

    def stale(*a, **k):
        raise StaleDraft("changed")

    monkeypatch.setattr(ctx.r.plans.kernel, "apply_replan", stale)
    with pytest.raises(ProposalStale):
        ctx.r.accept(STUDENT, pid)
    from app.os.replan.store import OverrideStore

    assert OverrideStore(ctx.engine, TENANT).active(ctx.plan_id) == []
    assert ProposalStore(ctx.engine, TENANT).get(pid).status == "pending"


def test_accept_refused_after_contract_changed(ctx):
    """Final review I4: the student reordered their programmes since: accepting is refused even if the op still fits."""
    pid = ctx.run(ctx.event("admission_rejected", programme_ref=P1))["proposal_id"]
    flip = lambda c: [p.model_copy(update={"rank": len(c.programmes) + 1 - p.rank}) for p in c.programmes]  # noqa: E731
    ctx.r.plans.change_programmes(ctx.plan_id, flip, "programmes:reorder")
    with pytest.raises(ProposalStale):
        ctx.r.accept(STUDENT, pid)


def test_refused_proposal_finishes_its_case_after_a_crash(ctx):
    """Final review I6: a crash between the refusal and the case/pause is finished on the step's retry."""
    with ctx.engine.begin() as conn:
        n = conn.execute(select(models.plans.c.current_revision).where(models.plans.c.id == ctx.plan_id)).scalar()
        for i, cause in enumerate(["replan:90", "replan:91", "replan:92"], n + 1):
            conn.execute(REV.insert().values(tenant_id=TENANT, plan_id=ctx.plan_id, number=i, cause=cause, diff={},
                                             created_at=NOW - timedelta(hours=1)))
    eid = ctx.event("approved_changed", template_key="review_visa_file", programme_ref=None)
    from app.os.replan.ops import AddTask

    op = AddTask(template_key="review_visa_file", reason="Again.")
    assert ctx.r.decide(ctx.plan_id, [eid], "rules", [op]).status == "paused"
    with ctx.engine.begin() as conn:  # the crash: the case and the pause were lost
        conn.execute(models.support_cases.delete())
    ctx.r.plans.kernel.set_changes_paused(ctx.plan_id, False)
    with ctx.engine.begin() as conn:  # (and the resume must not give a fresh allowance in this simulation)
        conn.execute(models.events.delete().where(models.events.c.type == "changes_resumed"))
    ctx.r.decide(ctx.plan_id, [eid], "rules", [op])  # the step's retry
    assert ctx.r.plans.kernel.changes_paused(ctx.plan_id)
    assert len(SupportStore(ctx.engine, TENANT).list("open")) == 1


def test_job_survives_one_bad_plan(ctx, monkeypatch):
    """Final review I9: one plan that fails its sweep never stops the others."""
    from app.os.replan.run import run_replan_job

    def boom(plan_id):
        raise RuntimeError("no playbook")

    monkeypatch.setattr(ctx.r.plans, "check_newer", boom)
    ctx.event("document_missing", instance_key="travel_insurance")
    assert run_replan_job(ctx.r, ctx.client, NOW) == 1


def test_upgrade_only_to_an_existing_version(ctx):
    """Self-found + final review minor (invariant 10): an upgrade to a version that does not exist is refused."""
    eid = ctx.event("playbook_newer", version=99)
    assert ctx.run(eid)["status"] == "refused"
    assert len(SupportStore(ctx.engine, TENANT).list("open")) == 1
