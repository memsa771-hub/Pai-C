"""Slice 8 Task 5: the PlanSource port (spec §2.2, S8-D6, S8-D9): the host submits a decision export; PAI OS only
stores it. Fictional data."""

import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select

from app.os import models, ports
from app.os.adapters.counsellor.run import run_intake_job
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.services import make_services
from app.os.ports.plan_source import export_sha256, set_sweep_mark, submit_counsellor_decision, sweep_mark
from app.os.settings import load_settings

SAMPLES = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "samples"


def sample(name: str = "export_valid_de.json", **over) -> dict:
    return {**json.loads((SAMPLES / name).read_text()), **over}


def switch_on(engine) -> None:
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))


@pytest.fixture
def mounted(engine, clean, os_db):
    ports.configure(make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine))
    try:
        yield engine
    finally:
        ports.configure(None)


def rows(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.counsellor_intake)).scalar()


def test_submit_stores_once(mounted):
    switch_on(mounted)
    assert submit_counsellor_decision(sample()) == "stored"
    assert submit_counsellor_decision(sample(programmes=[{"programme_ref": "ovgu-eeit", "rank": 1}])) == "duplicate"
    got = IntakeStore(mounted, "pai").get("d-sample-1")
    assert got.status == "pending" and got.export == sample()  # the first copy stays
    assert len(got.export_sha256) == 64 and rows(mounted) == 1


def test_export_sha_is_canonical(mounted):
    reordered = dict(reversed(list(sample().items())))
    assert export_sha256(reordered) == export_sha256(sample())  # key order does not matter
    assert export_sha256(sample(level="phd")) != export_sha256(sample())
    submit_counsellor_decision(reordered)
    assert IntakeStore(mounted, "pai").get("d-sample-1").export_sha256 == export_sha256(sample())


def test_concurrent_submit_one_row(mounted):
    switch_on(mounted)
    got, gate = [], threading.Barrier(2)

    def submit() -> None:
        gate.wait()
        got.append(submit_counsellor_decision(sample()))

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(got) == ["duplicate", "stored"] and rows(mounted) == 1  # review focus 2


def test_module_off_keeps_pending(mounted):
    assert submit_counsellor_decision(sample()) == "module_off"  # stored anyway, for when it is switched on
    assert IntakeStore(mounted, "pai").get("d-sample-1").status == "pending"
    assert run_intake_job(mounted, "pai", client=None) == 0  # off: nothing is enqueued


def test_submit_refuses_an_export_it_cannot_store(mounted):
    with pytest.raises(ValueError, match="decision_id"):
        submit_counsellor_decision({"schema": "pai.decision_record.v1"})
    assert rows(mounted) == 0


def test_sweep_mark_port(mounted):
    assert sweep_mark() is None
    set_sweep_mark({"chosen_at": "2027-01-10T04:00:00+00:00", "decision_id": "d-sample-1"})
    assert sweep_mark() == {"chosen_at": "2027-01-10T04:00:00+00:00", "decision_id": "d-sample-1"}


def test_unavailable_when_not_mounted():
    ports.configure(None)
    with pytest.raises(ports.OsUnavailable):
        submit_counsellor_decision(sample())
