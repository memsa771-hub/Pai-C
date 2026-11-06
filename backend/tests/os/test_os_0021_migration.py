"""P1-T6 Task 1: migration os_0021 (proposal status `requested`, source `student`, request columns, adoption table).
Fictional data."""

import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, insert
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from tests.os.conftest import BACKEND, run_alembic

pytestmark = pytest.mark.req("R-07")


def _proposal(engine, plan_id: int, **values) -> None:
    base = dict(tenant_id="pai", plan_id=plan_id, source="rules", status="pending")
    with engine.begin() as conn:
        conn.execute(insert(models.proposals).values(**{**base, **values}))


def _plan(engine, ref: str = "j-1:XX:master") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref=ref, student_ref="stu-1",
            contract={}, contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def test_os_0021_upgrade_downgrade(os_db, engine, clean):
    p = _plan(engine)
    _proposal(engine, p, status="requested", source="student", request_outcome="stale")  # allowed after the upgrade
    with pytest.raises(IntegrityError):
        _proposal(engine, p, request_outcome="maybe")  # the outcome has a check
    cols = {c["name"] for c in inspect(engine).get_columns("os_proposals", schema=OS_SCHEMA)}
    assert {"base_decision_version", "requested_version", "request_outcome"} <= cols
    assert "os_plan_adoptions" in inspect(engine).get_table_names(schema=OS_SCHEMA)

    engine.dispose()
    run_alembic(["downgrade", "os_0020"], os_db)
    try:
        eng = create_engine(os_db)
        try:
            assert "os_plan_adoptions" not in inspect(eng).get_table_names(schema=OS_SCHEMA)
            cols = {c["name"] for c in inspect(eng).get_columns("os_proposals", schema=OS_SCHEMA)}
            assert not cols & {"base_decision_version", "requested_version", "request_outcome"}
            plan = _plan(eng, "j-2:XX:master")
            with pytest.raises(IntegrityError):
                _proposal(eng, plan, status="requested")  # the old check refuses the new status
            with pytest.raises(IntegrityError):
                _proposal(eng, plan, source="student")
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)


def test_one_os_head():
    done = subprocess.run([sys.executable, "scripts/check_alembic_heads.py"], cwd=BACKEND, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout
