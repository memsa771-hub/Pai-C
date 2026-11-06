"""P1-T9 Task 2: with My plan off nothing changes. The route answers like a route that does not exist, and turning the
part on adds nothing to any existing answer (spec section 4: flags off, bytes the same)."""

import time

import pytest
from sqlalchemy import select

from app.os import models
from app.os.ports import my_plan as my_plan_port
from tests.os.test_api_packs import api as packs_api  # noqa: F401 - the real DBOS-backed pack app
from tests.os.test_golden import TEST_STUDENT
from tests.os.test_my_plan_api import P, counsellor_plan, make_api, me, self_plan

pytestmark = pytest.mark.req("R-53")


@pytest.fixture
def off(engine, clean, os_db):
    c = make_api(engine, os_db, on=False)
    yield c
    my_plan_port.configure(None)


def same_as_unknown(api):
    ref = api.get(f"{P}/no-such-route", headers=me())
    got = api.get(f"{P}/plan", headers=me())
    assert (got.status_code, got.json()) == (ref.status_code, ref.json()) == (404, {"detail": "Not Found"})


def test_plan_404_when_port_unconfigured(off):
    my_plan_port.configure(None)
    same_as_unknown(off)


def test_plan_404_when_host_says_off(off):
    my_plan_port.configure(lambda: False)
    same_as_unknown(off)
    my_plan_port.configure(lambda: 1 / 0)  # a host that raises reads as off
    same_as_unknown(off)


def stable(api, path, headers, timeout: float = 60) -> tuple[int, bytes]:
    """The answer once two reads in a row are equal (a pack or visa file is built in the background)."""
    end, last = time.monotonic() + timeout, None
    while time.monotonic() < end:
        r = api.get(P + path, headers=headers)
        now = (r.status_code, r.content)
        if now == last and b'"building"' not in r.content:
            return now
        last = now
        time.sleep(0.5)
    raise AssertionError(f"{path} did not settle")


def test_existing_responses_unchanged_with_my_plan_on(off):
    self_plan(off, "stu-1", "PK", "IE", "master")
    paths = ["/inbox", "/programmes", "/routes", "/eligibility/p1?route=ireland_master&intake=2027"]
    before = {p: (lambda r: (r.status_code, r.content))(off.get(P + p, headers=me())) for p in paths}
    my_plan_port.configure(lambda: True)
    after = {p: (lambda r: (r.status_code, r.content))(off.get(P + p, headers=me())) for p in paths}
    assert before == after


def test_pack_and_visa_bytes_unchanged_with_my_plan_on(packs_api):
    api, headers = packs_api, {"X-Test-Student": TEST_STUDENT.student_ref}
    my_plan_port.configure(None)
    before = {p: stable(api, p, headers) for p in ("/packs", "/visa")}
    with api.engine.connect() as conn:
        stored = conn.execute(select(models.artifact_versions.c.artifact_id, models.artifact_versions.c.number,
                                  models.artifact_versions.c.sha256).order_by(models.artifact_versions.c.id)).all()
    my_plan_port.configure(lambda: True)
    after = {p: stable(api, p, headers) for p in ("/packs", "/visa")}
    with api.engine.connect() as conn:
        stored_after = conn.execute(select(models.artifact_versions.c.artifact_id, models.artifact_versions.c.number,
                                  models.artifact_versions.c.sha256).order_by(models.artifact_versions.c.id)).all()
    import json
    for k in before:
        if before[k] != after[k]:
            a, b = json.loads(before[k][1]), json.loads(after[k][1])
            print("DIFF", k, [(x.get("programme_ref"), x.get("status")) for x in a["programmes"]], [(x.get("programme_ref"), x.get("status")) for x in b["programmes"]])
    assert before == after
    assert stored == stored_after  # the stored manifest bytes the approvals bind to
    my_plan_port.configure(None)
