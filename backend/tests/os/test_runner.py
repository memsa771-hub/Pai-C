import time
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select, update

from app.os import models
from app.os.compiler import compile_plan
from app.os.kernel import Kernel
from app.os.playbooks import Playbook, load_playbook
from app.os.runner import (
    Module,
    Registry,
    dbos_config,
    default_registry,
    enqueue_pending,
    reconcile,
)
from app.os.settings import load_settings
from tests.os.kernel_helpers import contract
from tests.os.runner_helpers import SLEEP_MODULE

FAKE_IE = load_playbook(__import__("pathlib").Path(__file__).parent / "playbooks" / "ireland_master.v1.yaml")


def work_playbook(task_type: str, n: int = 1) -> Playbook:
    return Playbook.model_validate({
        "key": "work_only", "version": 1, "route": {"origin": "PK", "destination": "IE", "level": "master"},
        "default_timezone": "Europe/Dublin",
        "tasks": [{"template_key": f"w{i}", "task_type": task_type, "title": f"Work {i}", "kind": "work"}
                  for i in range(n)],
    })


def start_plan(kernel: Kernel, task_type: str, n: int = 1, external_ref: str = "ext-1") -> int:
    draft = compile_plan(contract(external_ref=external_ref), work_playbook(task_type, n), {}, {}, date(2027, 3, 1))
    return kernel.create_plan(contract(external_ref=external_ref), draft).plan_id


def wait_states(engine, plan_id, wanted: set[str], timeout=40.0) -> list[str]:
    deadline = time.monotonic() + timeout
    while True:
        with engine.connect() as conn:
            states = conn.execute(select(models.tasks.c.state).where(models.tasks.c.plan_id == plan_id)).scalars().all()
        if states and set(states) <= wanted:
            return states
        if time.monotonic() > deadline:
            raise AssertionError(f"tasks stuck in {states}")
        time.sleep(0.2)


def test_double_owner_rejected():
    reg = Registry()
    reg.register(Module("a", frozenset({"x"}), None))
    with pytest.raises(ValueError, match="already owned"):
        reg.register(Module("b", frozenset({"x"}), None))


def test_unowned_playbook_type_rejected():
    reg = Registry()
    reg.register(Module("milestone", frozenset({"system.milestone"}), None))
    with pytest.raises(ValueError, match="student.act"):
        reg.validate([FAKE_IE])


def test_default_registry_owns_fake_routes():
    default_registry().validate([FAKE_IE])


def test_local_executor_id_refused():
    s = load_settings({"DATABASE_URL": "postgresql://x/y"})
    for bad in ("", "local", None):
        with pytest.raises(ValueError, match="executor"):
            dbos_config(s, bad)
    assert dbos_config(s, "w1")["executor_id"] == "w1"
    assert dbos_config(s, "w1")["application_version"] == "os-1"


def test_milestone_runs_to_done(dbos_worker, engine, clean):
    client, kernel = dbos_worker
    plan_id = start_plan(kernel, "system.milestone")
    assert enqueue_pending(engine, client) == 1
    assert wait_states(engine, plan_id, {"done"}) == ["done"]
    with engine.connect() as conn:
        att = conn.execute(select(models.task_attempts)).one()
        sent = conn.execute(select(models.enqueue_requests.c.sent)).scalar_one()
    assert (att.attempt, att.status, sent) == (1, "done", True)


def test_enqueue_twice_runs_once(dbos_worker, engine, clean):
    client, kernel = dbos_worker
    plan_id = start_plan(kernel, "test.sleep")
    enqueue_pending(engine, client)
    with engine.begin() as conn:  # crash before 'sent' was recorded: the request is sent again
        conn.execute(update(models.enqueue_requests).values(sent=False))
    assert enqueue_pending(engine, client) == 1
    wait_states(engine, plan_id, {"done"})
    with engine.connect() as conn:
        runs = conn.execute(select(func.count()).select_from(models.task_attempts)).scalar_one()
    assert runs == 1
    assert len(client.list_workflows(workflow_id_prefix="1:", load_input=False, load_output=False)) == 1


def test_reconcile_reenqueues_lost_request(dbos_worker, engine, clean):
    client, kernel = dbos_worker
    plan_id = start_plan(kernel, "system.milestone")
    with engine.begin() as conn:  # the enqueuer "died": marked sent but never reached DBOS
        conn.execute(update(models.enqueue_requests).values(sent=True))
    counts = reconcile(engine, client, kernel)
    assert counts["reenqueued"] == 1
    wait_states(engine, plan_id, {"done"})


def test_reconcile_fails_errored_workflow(dbos_worker, engine, clean):
    client, kernel = dbos_worker
    plan_id = start_plan(kernel, "test.fail")
    enqueue_pending(engine, client)
    deadline = time.monotonic() + 60
    while not client.list_workflows(workflow_ids=["1:1"], status="ERROR", load_input=False, load_output=False):
        assert time.monotonic() < deadline, "workflow never errored"
        time.sleep(0.3)
    assert reconcile(engine, client, kernel)["failed_workflows"] == 1
    with engine.connect() as conn:
        task = conn.execute(select(models.tasks)).one()
    assert (task.state, task.result["reason"]) == ("failed", "workflow_error")
    assert wait_states(engine, plan_id, {"failed"}) == ["failed"]
