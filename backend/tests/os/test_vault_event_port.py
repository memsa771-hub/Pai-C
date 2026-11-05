"""P1-T4 Task 1: the StudentFacts port takes a Vault event (VaultEventV1) and stores it once per student and version
(R-13). Postgres."""

import types
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.os import ports
from app.os.adapters.counsellor import manifest
from app.os.ports import student_facts

pytestmark = pytest.mark.req("R-13")

TENANT = "t1"


def event(version=1, keys=("constraint.budget",), student="s-1"):
    return {"schema": "pai.vault_event.v1", "key": f"vault_event:{student}:{version}", "student_ref": student,
            "vault_version": version, "kind": "student_fact_changed", "keys": list(keys),
            "at": datetime(2026, 11, 5, tzinfo=timezone.utc).isoformat()}


@pytest.fixture
def mounted(engine, clean):
    ports.configure(types.SimpleNamespace(engine=engine, settings=types.SimpleNamespace(tenant_id=TENANT)))
    manifest.set_enabled(engine, TENANT, True)
    try:
        yield engine
    finally:
        ports.configure(None)


def test_stores_then_reports_a_repeat_as_duplicate(mounted):
    assert student_facts.record_event(event()) == "stored"
    assert student_facts.record_event(event()) == "duplicate"
    with mounted.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM os.os_vault_events")).scalar() == 1


def test_one_row_per_student_and_version(mounted):
    assert student_facts.record_event(event(1)) == "stored"
    assert student_facts.record_event(event(2)) == "stored"
    assert student_facts.record_event(event(1, student="s-2")) == "stored"
    assert student_facts.latest_vault_version("s-1") == 2
    assert student_facts.latest_vault_version("s-2") == 1
    assert student_facts.latest_vault_version("nobody") is None


def test_module_off_still_stores(mounted):
    manifest.set_enabled(mounted, TENANT, False)
    assert student_facts.record_event(event()) == "module_off"
    assert student_facts.latest_vault_version("s-1") == 1


def test_an_invalid_event_is_refused_and_not_stored(mounted):
    for bad in ({**event(), "keys": []}, {**event(), "vault_version": 0}, {**event(), "kind": "other"},
                {**event(), "extra": 1}, {**event(), "keys": ["Bad Key"]}):
        with pytest.raises(ValueError):
            student_facts.record_event(bad)
    assert student_facts.latest_vault_version("s-1") is None
