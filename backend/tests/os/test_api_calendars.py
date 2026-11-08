"""P2-T11: the admin read API of the official calendars. Fictional data."""

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.os.api import build_router, make_services
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import load_playbook_dir
from app.os.registry.calendars import record_calendar, record_calendar_date
from app.os.registry.model import RegistryEntry
from app.os.registry.store import RegistryStore
from app.os.settings import load_settings
from tests.os.registry.helpers import AT, child, olist
from tests.os.test_api import ADMIN, FAKE, TOKEN, as_student

pytestmark = pytest.mark.req("R-33")
URL = "https://results.alpha.test/calendar"
CHECKED = datetime(2026, 10, 17, tzinfo=UTC)


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    reg, kb = RegistryStore(engine, "pai"), SqlKnowledge(engine, "pai")
    reg.record(olist(), cause="import")
    reg.record(child("admission_body", "body", "alpha-board", None, region="national"), cause="import")
    for slug, ctype in (("alpha-results", "result"), ("alpha-exams", "exam")):
        record_calendar(reg, RegistryEntry(entity_id=f"cal:{slug}", kind="calendar", name=f"Alpha {ctype}",
                                           parent_id="body:alpha-board", source_url=URL, quote="q", checked_at=AT),
                        ctype, cause="import")
    record_calendar_date(reg, kb, "cal:alpha-results", "result_date", date(2031, 5, 20), tz="Etc/UTC", url=URL,
                         quote="Result day", checked_at=CHECKED, intake_year=2031, intake_term="main", cause="import")
    record_calendar_date(reg, kb, "cal:alpha-exams", "exam_date", date(2031, 3, 2), url=URL, quote="", checked_at=CHECKED,
                         intake_year=2031, intake_term="main", status="unconfirmed", cause="import")
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    return TestClient(app)


def test_admin_only(api):
    url = "/v1/os/admin/registry/calendars?intake_year=2031"
    assert api.get(url).status_code == 401 and api.get(url, headers=as_student()).status_code == 401
    assert api.get("/v1/os/admin/registry/calendars", headers=ADMIN).status_code == 422  # the intake year is required


def test_calendars_with_their_dates_and_levels(api):
    r = api.get("/v1/os/admin/registry/calendars", params={"intake_year": 2031}, headers=ADMIN).json()
    by = {c["entity_id"]: c for c in r["calendars"]}
    res = by["cal:alpha-results"]
    assert (res["calendar_type"], res["parent_id"]) == ("result", "body:alpha-board")
    assert res["dates"]["result_date"]["date"] == "2031-05-20" and res["dates"]["result_date"]["tz"] == "Etc/UTC"
    assert res["dates"]["result_date"]["level"] == "not_confirmed"  # a high-stakes date shows as fact only when verified
    assert by["cal:alpha-exams"]["dates"]["exam_date"]["level"] == "not_confirmed"
    other = api.get("/v1/os/admin/registry/calendars", params={"intake_year": 2032}, headers=ADMIN).json()
    assert all(c["dates"] == {} for c in other["calendars"])
    one = api.get("/v1/os/admin/registry/calendars", params={"intake_year": 2031, "parent_id": "body:none"},
                  headers=ADMIN).json()
    assert one["calendars"] == []
