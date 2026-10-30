"""Slice 8 crash test (spec §6, §8): SIGKILL the worker between the intake's `process` step and its `finish` step.
DBOS recovers the workflow; the saved `process` result is not run again, so there is one plan, its `created`
revision only, and the intake row ends `planned`. Fictional export; real worker subprocesses (Linux CI)."""

import json
import time
from pathlib import Path

import pytest
from dbos import DBOSClient
from sqlalchemy import func, insert, select, text

from app.os import models
from app.os.adapters.counsellor.run import enqueue_intake
from app.os.adapters.counsellor.store import IntakeStore
from app.os.runner import APP_NAME
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_crash import Pool, _wait_queue

pytestmark = pytest.mark.chaos
SAMPLES = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "samples"
TIMEOUT_S = 120


def _finish_waiting(engine) -> bool:
    """True while a worker's `finish` step waits on the intake row the test holds."""
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
            "AND query ILIKE 'UPDATE os.os_counsellor_intake%'")).scalar_one() > 0


def test_crash_during_counsellor_intake(os_db, engine, clean, tmp_path):
    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed

    reset_dbos_schema(os_db)
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    load_programme_seed(PROGRAMME_SEED, ProgrammeStore(engine, "pai"))
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    store = IntakeStore(engine, "pai")
    store.add(json.loads((SAMPLES / "export_valid_de.json").read_text()), "0" * 64)
    pool, client, held = Pool(os_db, tmp_path), None, None
    try:
        pool.start(0)
        client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
        _wait_queue(client, pool)  # before the lock: DBOS's startup migrations wait for open transactions
        held = engine.connect()  # holds the intake row: `process` runs, `finish` waits on it
        held.execute(select(models.counsellor_intake).where(
            models.counsellor_intake.c.decision_id == "d-sample-1").with_for_update())
        enqueue_intake(client, "pai", "d-sample-1")
        deadline = time.monotonic() + TIMEOUT_S
        while not _finish_waiting(engine):
            assert time.monotonic() < deadline, f"finish never waited (logs: {tmp_path})"
            time.sleep(0.2)
        with engine.connect() as conn:  # `process` is done: the plan exists, the row is still pending
            assert conn.execute(select(func.count()).select_from(models.plans)).scalar() == 1
        pool.kill(0)
        held.rollback()  # let go: the restarted worker recovers the workflow and runs `finish`
        held.close()
        held = None
        pool.start(0)
        while store.get("d-sample-1").status == "pending":
            assert time.monotonic() < deadline, f"not finished after the restart (logs: {tmp_path})"
            time.sleep(0.5)
    finally:
        if held is not None:
            held.close()
        pool.stop_all()
        if client is not None:
            client.destroy()
    got = store.get("d-sample-1")
    with engine.connect() as conn:
        plans = conn.execute(select(models.plans.c.id)).scalars().all()
        causes = conn.execute(select(models.plan_revisions.c.cause)).scalars().all()
    assert (got.status, got.plan_id) == ("planned", plans[0]) and len(plans) == 1
    assert causes == ["created"]  # nothing ran twice
