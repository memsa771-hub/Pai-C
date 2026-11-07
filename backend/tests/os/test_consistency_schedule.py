"""P1-T10 A3 (R-05, Q2): the nightly job runs once per date and its next time comes from the setting."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app import pai_os_bridge as bridge
from app.config import config
from app.os import ports
from app.os.ports import consistency as port
from tests.os.test_connect_t5_flow import svc  # noqa: F401 - fixture

pytestmark = pytest.mark.req("R-05")
UTC = timezone.utc


def test_the_next_run_time_is_computed_from_the_setting():
    at = lambda *a: datetime(*a, tzinfo=UTC)  # noqa: E731
    assert bridge.next_consistency_run(at(2027, 3, 1, 10, 0), 21) == at(2027, 3, 1, 21, 0)
    assert bridge.next_consistency_run(at(2027, 3, 1, 21, 0), 21) == at(2027, 3, 2, 21, 0)  # exactly due: tomorrow
    assert bridge.next_consistency_run(at(2027, 3, 1, 23, 59), 21) == at(2027, 3, 2, 21, 0)
    assert bridge.next_consistency_run(at(2027, 3, 31, 23, 0), 0) == at(2027, 4, 1, 0, 0)


def test_the_setting_defaults_to_21_utc():
    assert config.CONNECT_CONSISTENCY_HOUR_UTC == 21


def test_two_claims_for_one_date_make_one_run(svc):  # noqa: F811
    ports.configure(svc)
    try:
        day = date(2027, 3, 1)
        first = port.claim_run(day, "nightly")
        assert first is not None and port.claim_run(day, "nightly") is None
    finally:
        ports.configure(None)


def test_the_nightly_job_runs_once_per_date_and_only_while_on(svc, engine):  # noqa: F811
    from sqlalchemy import insert

    from app.os import models
    from scripts.counselor_eval_support import StudentSession

    day = date(2027, 3, 1)
    ports.configure(svc)
    try:
        with StudentSession() as student, student.factory() as db, \
                patch.object(config, "CONNECT_HANDOFF", True, create=True):
            assert bridge.consistency_nightly(db, day) is None  # the module is off: the date is not used up
            assert port.claim_run(day, "probe") is not None
            with engine.begin() as conn:
                conn.execute(models.consistency_runs.delete())
                conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
            first = bridge.consistency_nightly(db, day)
            assert first is not None and first["errors"] == 0
            assert bridge.consistency_nightly(db, day) is None  # the same date: the second replica loses
            assert bridge.consistency_nightly(db, date(2027, 3, 2)) is not None
            with engine.connect() as conn:
                last = conn.execute(models.consistency_runs.select().order_by(models.consistency_runs.c.run_date)).all()
            assert [r.run_date for r in last] == [day, date(2027, 3, 2)] and all(r.finished_at for r in last)
    finally:
        ports.configure(None)
