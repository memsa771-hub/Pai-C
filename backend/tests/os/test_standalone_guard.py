"""P1-T10 Task D1 (R-59, R-09): the standalone guard. With no `counsellor` module row on, PAI OS answers every P1 port
with its standalone value: nothing is read from, handed to or asked of the Counsellor. The test also fails when the
standalone job's database has the module on, because then the `-m standalone` job would prove nothing about P1."""

import types

import pytest
from sqlalchemy import select

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.ports import (choice_requests, choice_sink, document_files, escalation, fact_questions, my_plan, os_events,
                          plan_source, student_facts)

pytestmark = [pytest.mark.standalone, pytest.mark.req("R-59"), pytest.mark.req("R-09")]

TENANT = "pai"


@pytest.fixture
def standalone(engine, clean):
    ports.configure(types.SimpleNamespace(engine=engine, settings=types.SimpleNamespace(tenant_id=TENANT)))
    try:
        yield engine
    finally:
        ports.configure(None)


def test_the_standalone_database_has_no_module_on(standalone):
    """The canary: no `counsellor` row is on in the database this job runs against."""
    with standalone.connect() as conn:
        on = conn.execute(select(models.modules.c.module).where(models.modules.c.enabled.is_(True))).scalars().all()
    assert on == []
    assert manifest.is_enabled(standalone, TENANT) is False
    assert plan_source.counsellor_enabled() is False


def test_every_p1_port_answers_its_standalone_value(standalone):
    # The Counsellor is not asked and has nothing to hand over.
    assert plan_source.latest_version("stu-1") is None
    assert student_facts.get("stu-1").facts == [] and student_facts.latest_vault_version("stu-1") is None
    assert student_facts.record_event({
        "schema": "pai.vault_event.v1", "key": "vault_event:stu-1:1", "student_ref": "stu-1", "vault_version": 1,
        "kind": "student_fact_changed", "keys": ["constraint.budget"], "at": "2026-11-05T00:00:00+00:00"}
    ) == "module_off"  # stored, and no replan is recorded
    assert os_events.pending_events() == []
    assert escalation.pending_counsellor_escalations() == []
    # The gates read as off, and an unconfigured port is today's route.
    assert choice_sink.enabled() is False and choice_sink.request("stu-1", "XX", "YY", "master", {}, []) is None
    assert choice_requests.enabled() is False
    assert my_plan.enabled() is False
    assert document_files.enabled() is False
    with pytest.raises(KeyError):
        document_files.read("stu-1", "file-1")
    assert fact_questions.conflicts("stu-1") == {} and fact_questions.read("stu-1") is None
    # And nothing was written for the Counsellor.
    with standalone.connect() as conn:
        assert conn.execute(select(models.outbox.c.id).where(models.outbox.c.channel == "counsellor")).all() == []
        assert conn.execute(select(models.plans.c.id).where(models.plans.c.source == "counsellor")).all() == []
