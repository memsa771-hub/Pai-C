"""P1-T9 Task 2: with My plan off nothing changes. The route answers like a route that does not exist, and turning the
part on adds nothing to any existing answer (spec section 4: flags off, bytes the same)."""

import json
import time

import pytest
from sqlalchemy import select

from app.os import models
from app.os.ports import my_plan as my_plan_port
from tests.os.test_api_visa import ME
from tests.os.test_api_visa import api as visa_api  # noqa: F401 - the real DBOS-backed pack and visa app
from tests.os.test_visa_run import ready_visa
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


def manifests(api) -> list:
    av = models.artifact_versions
    with api.engine.connect() as conn:
        return conn.execute(select(av.c.artifact_id, av.c.number, av.c.sha256).order_by(av.c.id)).all()


def test_pack_and_visa_bytes_unchanged_with_my_plan_on(visa_api):
    """A real visa file (the student's visa choice and documents are in place) and the pack list: their bytes and the
    stored manifest SHA-256s the approvals bind to are the same with the part on."""
    api = visa_api
    ready_visa(api.ctx)
    my_plan_port.configure(None)
    try:
        before = {p: stable(api, p, ME) for p in ("/packs", "/visa")}
        stored = manifests(api)
        assert stored, "no manifest was stored: the proof would compare nothing"
        visa = json.loads(before["/visa"][1])
        assert visa["programme_ref"] and visa["checklist"] and visa["files"]
        my_plan_port.configure(lambda: True)
        after = {p: stable(api, p, ME) for p in ("/packs", "/visa")}
        assert before == after
        assert manifests(api) == stored
    finally:
        my_plan_port.configure(None)


def test_plan_404_without_the_student_header_while_off(off):
    """The gate runs before the sign-in check: off, an unauthenticated call gets the plain 404 too."""
    ref = off.get(f"{P}/no-such-route")
    got = off.get(f"{P}/plan")
    assert (got.status_code, got.json()) == (ref.status_code, ref.json()) == (404, {"detail": "Not Found"})
