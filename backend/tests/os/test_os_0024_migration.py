"""P1-T10 A1: migration os_0024 (`os_consistency_cases` and `os_consistency_runs`). Fictional data."""

import subprocess
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from tests.os.conftest import BACKEND, run_alembic

pytestmark = pytest.mark.req("R-05")

CASE_COLUMNS = {"id", "tenant_id", "student_ref", "rule", "plan_id", "codes", "status", "resolution", "first_seen_at",
                "last_seen_at", "resolved_at"}
RUN_COLUMNS = {"id", "tenant_id", "run_date", "mode", "started_at", "finished_at", "counts"}


def _case(engine, **values) -> None:
    base = dict(tenant_id="pai", student_ref="stu-1", rule=1, codes=["no_plan"], status="open")
    with engine.begin() as conn:
        conn.execute(insert(models.consistency_cases).values(**{**base, **values}))


def test_os_0024_upgrade_downgrade(os_db, engine, clean):
    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("os_consistency_cases", schema=OS_SCHEMA)} == CASE_COLUMNS
    assert {c["name"] for c in insp.get_columns("os_consistency_runs", schema=OS_SCHEMA)} == RUN_COLUMNS
    engine.dispose()
    run_alembic(["downgrade", "os_0023"], os_db)
    try:
        eng = create_engine(os_db)
        try:
            tables = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
            assert not tables & {"os_consistency_cases", "os_consistency_runs"}
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)
    eng = create_engine(os_db)
    try:
        assert "os_consistency_cases" in inspect(eng).get_table_names(schema=OS_SCHEMA)
    finally:
        eng.dispose()


def test_one_open_case_per_student_and_rule(engine, clean):
    _case(engine)
    with pytest.raises(IntegrityError):
        _case(engine)
    _case(engine, rule=2)  # another rule
    _case(engine, student_ref="stu-2")  # another student
    _case(engine, status="resolved")  # a resolved one does not count
    _case(engine, status="resolved")


def test_checks_on_rule_and_status(engine, clean):
    for bad in ({"rule": 0}, {"rule": 9}, {"status": "closed"}):
        with pytest.raises(IntegrityError):
            _case(engine, **bad)


def test_plan_delete_keeps_the_case(engine, clean):
    with engine.begin() as conn:
        plan = conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref="j:XX:master", student_ref="stu-1", contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()
    _case(engine, plan_id=plan)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_plans"))
        assert conn.execute(text("SELECT plan_id FROM os.os_consistency_cases")).scalar_one() is None


def test_one_run_per_tenant_and_date(engine, clean):
    def run(tenant="pai", day=date(2027, 1, 1)):
        with engine.begin() as conn:
            conn.execute(insert(models.consistency_runs).values(tenant_id=tenant, run_date=day, mode="nightly"))

    run()
    with pytest.raises(IntegrityError):
        run()
    run(day=date(2027, 1, 2))
    run(tenant="other")


def test_one_os_head():
    done = subprocess.run([sys.executable, "scripts/check_alembic_heads.py"], cwd=BACKEND, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout
