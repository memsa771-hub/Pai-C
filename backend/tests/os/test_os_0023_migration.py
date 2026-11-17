"""P1-T8 Task 3: migration os_0023 (`os_student_requests`: one open request per student and fact). Fictional data."""

import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from tests.os.conftest import BACKEND, run_alembic

pytestmark = pytest.mark.req("R-19")

COLUMNS = {"id", "tenant_id", "student_ref", "plan_id", "task_id", "kind", "need_kind", "need_ref", "evidence",
           "status", "closed_cause", "created_at", "closed_at"}


def _plan(engine) -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref="j-1:XX:master", student_ref="stu-1",
            contract={}, contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def _row(engine, plan_id: int, **values) -> None:
    base = dict(tenant_id="pai", student_ref="stu-1", plan_id=plan_id, kind="provide", need_kind="fact",
                need_ref="education.matric.marks_obtained", evidence="stated", status="open")
    with engine.begin() as conn:
        conn.execute(insert(models.student_requests).values(**{**base, **values}))


def test_os_0023_upgrade_downgrade(os_db, engine, clean):
    cols = {c["name"] for c in inspect(engine).get_columns("os_student_requests", schema=OS_SCHEMA)}
    assert cols == COLUMNS
    names = {i["name"]: i for i in inspect(engine).get_indexes("os_student_requests", schema=OS_SCHEMA)}
    assert names["uq_os_student_requests_open"]["unique"] is True
    plan = _plan(engine)
    _row(engine, plan)
    for bad in ({"kind": "tick"}, {"need_kind": "value"}, {"evidence": "told"}, {"status": "closed"}):
        with pytest.raises(IntegrityError):  # every coded column has a check
            _row(engine, plan, need_ref="other", **bad)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_student_requests"))
    engine.dispose()
    run_alembic(["downgrade", "os_0022"], os_db)
    try:
        eng = create_engine(os_db)
        try:
            assert "os_student_requests" not in inspect(eng).get_table_names(schema=OS_SCHEMA)
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)
    eng = create_engine(os_db)
    try:
        assert "os_student_requests" in inspect(eng).get_table_names(schema=OS_SCHEMA)
    finally:
        eng.dispose()


def test_task_delete_keeps_the_row_and_plan_delete_removes_it(os_db, engine, clean):
    plan = _plan(engine)
    with engine.begin() as conn:
        task = conn.execute(insert(models.tasks).values(
            tenant_id="pai", plan_id=plan, instance_key="provide@fact:x:stated", template_key="provide",
            task_type="student.provide", kind="student", title="t", state="waiting_student", due_tz="UTC",
            playbook_version=1).returning(models.tasks.c.id)).scalar_one()
    _row(engine, plan, task_id=task)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_tasks"))
        assert conn.execute(text("SELECT task_id FROM os.os_student_requests")).scalar_one() is None
        conn.execute(text("DELETE FROM os.os_plans"))
        assert conn.execute(text("SELECT count(*) FROM os.os_student_requests")).scalar() == 0


def test_one_os_head():
    done = subprocess.run([sys.executable, "scripts/check_alembic_heads.py"], cwd=BACKEND, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout
