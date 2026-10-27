"""The `os.replan` DBOS workflow (Slice 7 spec §2, S7-D12): one run per (plan, event, pause generation).

Steps: `load` (is there anything to do) -> `rules` -> the Supervisor (only on a hand-over, its model calls are
DBOS steps) -> `decide` (kernel checks, limits, apply or propose) or `support` / `retry`. Steps return ids and
small JSON, never plan state. Step retries are the only retries (invariant 7); every write is keyed by the
proposal or the event (invariant 8)."""

import logging

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import Engine, func, select

from app.os import models
from app.os.knowledge.research.readings import AgentRuns, cost
from app.os.replan import events as ev
from app.os.replan.apply import Replanner, ops_of
from app.os.replan.rules import Handover, Retry, rules_for
from app.os.replan.supervisor import propose
from app.os.settings import OsSettings

REPLAN_WORKFLOW = "os.replan"
HANDOVER_PREFIX = "No automatic change: "  # no Supervisor configured (a system problem, Slice 8 S8-D12)
BUDGET_REASON = "The planning assistant's monthly budget is used up."
INVALID_REASON = "The planning assistant could not propose a valid change."
log = logging.getLogger("app.os.replan")


def replan_workflow_id(tenant_id: str, plan_id: int, event_id: int, generation: int = 0) -> str:
    """`generation` counts the plan's resumes, so an event held while changes were paused runs again after."""
    return f"replan:{tenant_id}:{plan_id}:{event_id}:g{generation}"


def generation(engine: Engine, tenant_id: str, plan_id: int) -> int:
    E = models.events
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(E).where(
            E.c.tenant_id == tenant_id, E.c.plan_id == plan_id, E.c.type == "changes_resumed")).scalar()


def enqueue_replan(client: DBOSClient, tenant_id: str, plan_id: int, event_id: int, generation: int = 0) -> str:
    from app.os.runner.workflow import APP_VERSION, QUEUE_NAME  # imported here: the runner imports replan

    wid = replan_workflow_id(tenant_id, plan_id, event_id, generation)
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": REPLAN_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options, plan_id, event_id)
    return wid


def register_replan(engine: Engine, settings: OsSettings, replanner: Replanner, supervisor=None) -> None:
    """Registers os.replan and its steps. Must run before DBOS.launch(). `supervisor` is (agent, spec), or None when
    no model key is set: then every hand-over becomes a support case."""
    from app.os.runner.workflow import STEP_CONFIG  # imported here: the runner imports replan

    tenant = settings.tenant_id
    runs = AgentRuns(engine, tenant)

    def load(plan_id: int, event_id: int) -> dict:
        e = ev.get(engine, tenant, event_id)
        if e is None or e.plan_id != plan_id:
            return {"skip": "missing"}
        done = replanner.proposals.for_event(event_id)
        if done is not None:
            return {"skip": done.status, "proposal_id": done.id}
        if replanner.support_cases.for_event(event_id) is not None:
            return {"skip": "support"}
        if replanner.plans.kernel.changes_paused(plan_id):
            return {"skip": "paused"}
        return {"type": e.type}

    def rules(plan_id: int, event_id: int) -> dict:
        e = ev.get(engine, tenant, event_id)
        got = rules_for(e, replanner.state(plan_id, with_suggestions=e.type == "admission_rejected"),
                        replanner.config(plan_id))
        if isinstance(got, Handover):
            return {"handover": got.reason}
        if isinstance(got, Retry):
            return {"retry": got.instance_key}
        return {"ops": [op.model_dump(mode="json") for op in got]}

    def decide(plan_id: int, event_id: int, source: str, raw_ops: list[dict]) -> dict:
        d = replanner.decide(plan_id, [event_id], source, ops_of(raw_ops))
        return {"status": d.status, "proposal_id": d.proposal_id}

    def support(plan_id: int, event_id: int, reason: str) -> dict:
        return {"status": "support", "case_id": replanner.support(plan_id, [event_id], reason)}

    def retry(plan_id: int, event_id: int, instance_key: str) -> dict:
        retried = replanner.retry(plan_id, instance_key)
        return {"status": "retried" if retried else "applied", "proposal_id": replanner.close(plan_id, [event_id])}

    def record(plan_id: int, reading: str, model: str, usage: dict, cost_usd: float, error: str | None) -> None:
        from pydantic_ai.usage import RunUsage

        runs.record(None, reading, spec=supervisor[1], model=model, usage=RunUsage(**usage), cost_usd=cost_usd,
                    error=error, plan_id=plan_id)

    def supervise_input(plan_id: int, event_id: int) -> dict:
        """What the Supervisor needs, checked for budget first (a step: the reads are not repeated on replay)."""
        spent = runs.month_spend(replanner.clock(), supervisor[1].id)
        return {"over_budget": spent >= settings.replan_monthly_usd}

    step = lambda name, fn: DBOS.step(name=f"os.replan.{name}", **STEP_CONFIG)(fn)  # noqa: E731
    load_step, rules_step, decide_step = step("load", load), step("rules", rules), step("decide", decide)
    support_step, retry_step, record_step = step("support", support), step("retry", retry), step("record", record)
    budget_step = step("budget", supervise_input)

    def replan(plan_id: int, event_id: int) -> dict:
        begun = load_step(plan_id, event_id)
        if "skip" in begun:
            return {"status": begun["skip"], "proposal_id": begun.get("proposal_id")}
        answer = rules_step(plan_id, event_id)
        if "retry" in answer:
            return retry_step(plan_id, event_id, answer["retry"])
        if "ops" in answer:
            return decide_step(plan_id, event_id, "rules", answer["ops"])
        if supervisor is None:
            return support_step(plan_id, event_id, f"{HANDOVER_PREFIX}{answer['handover']}.")
        if budget_step(plan_id, event_id)["over_budget"]:
            return support_step(plan_id, event_id, BUDGET_REASON)
        agent, spec = supervisor
        state = replanner.state(plan_id, with_suggestions=True)
        result = propose(agent, spec, state, [ev.get(engine, tenant, event_id)], [], replanner.plans._pinned(plan_id))
        usage = {"input_tokens": result.usage.input_tokens or 0, "cache_read_tokens": result.usage.cache_read_tokens or 0,
                 "output_tokens": result.usage.output_tokens or 0, "requests": result.usage.requests or 0}
        error = None if result.error is None else result.error.split(":", 1)[0]  # the kind only
        record_step(plan_id, f"{DBOS.workflow_id}:supervisor", agent.model.model_name, usage,
                    cost(result.usage, settings, spec.tier, agent.model.model_name), error)
        if result.output is None:
            return support_step(plan_id, event_id, INVALID_REASON)
        return decide_step(plan_id, event_id, "supervisor", [op.model_dump(mode="json") for op in result.output.ops])

    DBOS.workflow(name=REPLAN_WORKFLOW)(replan)


def run_replan_job(replanner: Replanner, client: DBOSClient, now) -> int:
    """Every 5 minutes (the worker's job): sweep for newer playbooks and changed approved files, expire answered-late
    proposals, then enqueue one replan per pending event of every plan whose changes are not paused."""
    engine, tenant = replanner.engine, replanner.tenant
    P = models.plans
    with engine.connect() as conn:
        plan_ids = conn.execute(select(P.c.id).where(P.c.tenant_id == tenant, P.c.status.in_(("active", "at_risk")))
                                .order_by(P.c.id)).scalars().all()
    for plan_id in plan_ids:  # one bad plan never stops the others (final review I9)
        try:
            replanner.plans.check_newer(plan_id)
            ev.detect_approved_changed(engine, tenant, plan_id)
        except Exception:  # noqa: BLE001  (logged; the plan is swept again in 5 minutes)
            log.exception("replan sweep failed for plan %s", plan_id)
    replanner.expire_due(now)
    queued = 0
    for e in ev.pending(engine, tenant):
        if replanner.plans.kernel.changes_paused(e.plan_id):
            continue
        enqueue_replan(client, tenant, e.plan_id, e.id, generation(engine, tenant, e.plan_id))
        queued += 1
    return queued
