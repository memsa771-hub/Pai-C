"""Review M3: every read and write is scoped to the caller's tenant (spec §4.10: every table carries tenant_id)."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.os import models
from app.os.api import build_router
from app.os.api.queries import plan_out
from app.os.kernel import Kernel
from app.os.runner import enqueue, enqueue_pending
from tests.os import test_workers as tw
from tests.os.kernel_helpers import contract, draft


def _other_tenant_plan(engine) -> tuple[int, int]:
    """A plan of tenant 't2' (playbook test_route v1): returns (plan_id, id of its ready milestone 'a')."""
    ref = Kernel(engine, "t2").create_plan(contract(external_ref="t2-ext"), draft())
    with engine.connect() as conn:
        a = conn.execute(select(models.tasks.c.id).where(
            models.tasks.c.plan_id == ref.plan_id, models.tasks.c.instance_key == "a")).scalar_one()
    return ref.plan_id, a


class FakeClient:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, options, task_id, attempt):
        self.enqueued.append((task_id, attempt))


def test_other_tenant_plan_not_visible_or_changeable(engine, clean):
    svc, _, kernel = tw.service(engine)  # tenant "pai"
    plan_id, task_id = _other_tenant_plan(engine)
    assert plan_out(engine, "pai", plan_id) is None
    for call in (lambda: svc.recompile(plan_id, "x"), lambda: svc.upgrade(plan_id),
                 lambda: svc._pinned(plan_id), lambda: kernel.revise(plan_id, "x", draft()),
                 lambda: kernel.mark_running(task_id, 1)):
        with pytest.raises(KeyError):
            call()


def test_enqueue_pending_only_own_tenant(engine, clean):
    _, other_task = _other_tenant_plan(engine)
    mine = Kernel(engine, "pai").create_plan(contract(external_ref="pai-ext"), draft()).plan_id
    with engine.connect() as conn:
        my_task = conn.execute(select(models.tasks.c.id).where(
            models.tasks.c.plan_id == mine, models.tasks.c.instance_key == "a")).scalar_one()
    client = FakeClient()
    assert enqueue_pending(engine, client, tenant_id="pai") == 1
    assert client.enqueued == [(my_task, 1)]
    with engine.connect() as conn:
        sent = dict(conn.execute(select(models.enqueue_requests.c.task_id, models.enqueue_requests.c.sent)).all())
    assert sent == {my_task: True, other_task: False}


def test_worker_ignores_other_tenant_task(dbos_worker, engine, clean):
    client, kernel = dbos_worker  # a worker of tenant "pai"
    _, other_task = _other_tenant_plan(engine)
    enqueue(client, other_task, 1)  # even if its workflow reaches this worker's queue
    time.sleep(3)
    with engine.connect() as conn:
        state = conn.execute(select(models.tasks.c.state).where(models.tasks.c.id == other_task)).scalar_one()
    assert state == "ready"


def test_upgrade_unknown_plan_is_404(engine, clean, os_db):
    from datetime import date

    from app.os.api import make_services
    from app.os.playbooks import load_playbook_dir
    from app.os.settings import load_settings
    from tests.os.test_api import FAKE

    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": "t", "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    r = TestClient(app).post("/v1/os/plans/999/upgrade", headers={"X-OS-Admin-Token": "t"})
    assert r.status_code == 404
