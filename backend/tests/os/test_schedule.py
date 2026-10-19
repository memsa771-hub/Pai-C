"""Review M14: a job registered with register_job really fires on its DBOS schedule.

Uses the same path as the worker (register_workflow -> register_job -> launch -> DBOS.apply_schedules)
with a once-a-second schedule, so the test does not wait for a minute boundary.
"""

import time

import pytest
from sqlalchemy import func, insert, select

from app.os import models
from app.os.kernel import Kernel
from app.os.runner import dbos_config, default_registry, launch, register_job, register_workflow
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema


@pytest.fixture
def scheduled(os_db, engine, clean):
    from dbos import DBOS

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})

    def probe() -> int:  # writes one event per run, so the test reads runs from the database
        with engine.begin() as conn:
            conn.execute(insert(models.events).values(tenant_id="pai", type="schedule_probe", payload={}))
        return 1

    DBOS(config=dbos_config(settings, "sched-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, "pai"))
    register_job("probe", "* * * * * *", probe)
    launch()
    try:
        yield DBOS
    finally:
        DBOS.destroy(destroy_registry=True)


def _runs(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.events).where(
            models.events.c.type == "schedule_probe")).scalar_one()


def test_registered_job_fires_on_schedule(scheduled, engine):
    names = {s["schedule_name"] if isinstance(s, dict) else s.schedule_name for s in scheduled.list_schedules()}
    assert "os.probe" in names
    deadline = time.monotonic() + 30
    while _runs(engine) < 2:
        assert time.monotonic() < deadline, "the scheduled job never fired"
        time.sleep(0.5)
    assert _runs(engine) >= 2  # fired repeatedly, on its own, with no test code calling it
