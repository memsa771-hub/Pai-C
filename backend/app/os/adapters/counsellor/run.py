"""The `counsellor.intake` DBOS workflow and its one-minute job (Slice 8 spec §2.3, S8-D2, S8-D9).

The job runs only while the `counsellor` module is on. Each tick it enqueues each student's oldest pending decision,
so one student's decisions are planned one at a time in `chosen_at` order and the newest decides which plan
remains. Workflow ID `counsellor:{tenant}:{decision_id}`: enqueuing the same decision again is a no-op. Steps:
`process` (Task 4: plan, revise, replace or refuse) then `finish` (the intake row's outcome). Step retries are the
only retries (invariant 7); both steps check the intake row first, so a repeat changes nothing (invariant 8)."""

from dataclasses import asdict, dataclass

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import Engine

from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.kernel import Kernel
from app.os.ports.escalation import EscalationSink

INTAKE_WORKFLOW = "counsellor.intake"


@dataclass(frozen=True)
class IntakeDeps:
    """What `process` needs; the API's Services also has these, so tests can pass either."""
    engine: Engine
    kernel: Kernel
    plans: object  # PlanService
    escalations: EscalationSink


def intake_workflow_id(tenant_id: str, decision_id: str) -> str:
    return f"counsellor:{tenant_id}:{decision_id}"


def enqueue_intake(client: DBOSClient, tenant_id: str, decision_id: str) -> str:
    from app.os.runner.workflow import APP_VERSION, QUEUE_NAME  # imported here: the runner imports the adapters

    wid = intake_workflow_id(tenant_id, decision_id)
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": INTAKE_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options, decision_id)
    return wid


def register_intake(deps) -> None:
    """Registers the workflow and its steps. Must run before DBOS.launch()."""
    from app.os.runner.workflow import STEP_CONFIG

    store = IntakeStore(deps.engine, deps.kernel.tenant_id)

    def plan_it(decision_id: str) -> dict:
        intake = store.get(decision_id)
        if intake is None or intake.status != "pending":
            return {"skip": intake.status if intake else "missing"}
        return asdict(process(deps, intake))

    def finish(decision_id: str, status: str, reason: str | None, plan_id: int | None) -> None:
        intake = store.get(decision_id)
        if intake is not None and intake.status == "pending":
            store.finish(intake.id, status, reason, plan_id)

    plan_step = DBOS.step(name="counsellor.intake.process", **STEP_CONFIG)(plan_it)
    finish_step = DBOS.step(name="counsellor.intake.finish", **STEP_CONFIG)(finish)

    def intake(decision_id: str) -> dict:
        result = plan_step(decision_id)
        if "skip" not in result:
            finish_step(decision_id, result["status"], result["reason"], result["plan_id"])
        return result

    DBOS.workflow(name=INTAKE_WORKFLOW)(intake)


def run_intake_job(engine: Engine, tenant_id: str, client: DBOSClient | None) -> int:
    """Every minute (the worker's job): enqueues each student's oldest pending decision. Off: nothing."""
    if not manifest.is_enabled(engine, tenant_id):
        return 0
    seen: set[str] = set()
    queued = 0
    for intake in IntakeStore(engine, tenant_id).pending(limit=500):
        if intake.student_ref in seen:
            continue
        seen.add(intake.student_ref)
        enqueue_intake(client, tenant_id, intake.decision_id)
        queued += 1
    return queued
