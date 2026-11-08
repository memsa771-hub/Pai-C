"""P2-T6: the admin API of the spreadsheet import (P2 spec §4.6; master R-67, R-68). Fictional data."""

from datetime import date

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.os.api import build_router, make_services
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.sheets.helpers import COUNTRY, fact, inst, load_list, workbook
from tests.os.test_api import ADMIN, FAKE, TOKEN, as_student

pytestmark = pytest.mark.req("R-68")
BASE = "/v1/os/admin/imports"
FORM = {"country": COUNTRY, "actor": "dev", "owner_accepted": "chat 2026-11-07"}


@pytest.fixture
def api(engine, clean, os_db, monkeypatch):
    from tests.os.sheets.helpers import FakeDisputes

    def wired(deps):  # the real allow-list and review queue are T3 and T5: fakes stand in
        deps.official, deps.disputes = (lambda url, scope: True), FakeDisputes()
        return deps

    monkeypatch.setattr("app.os.api.imports.wire_other_tasks", wired)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    load_list(engine)
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    return TestClient(app)


def upload(path):
    return {"file": (path.name, path.read_bytes(), "application/octet-stream")}


def test_admin_only(api, tmp_path):
    path = workbook(tmp_path, [inst(1)])
    assert api.get(BASE).status_code == 401 and api.get(BASE, headers=as_student()).status_code == 401
    assert api.post(BASE, data=FORM, files=upload(path), headers=as_student()).status_code == 401
    assert api.get(BASE + "/template").status_code == 401
    assert api.get(BASE, headers=ADMIN).json() == {"imports": []}


def test_template_download(api):
    r = api.get(BASE + "/template", headers=ADMIN)
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_validate_import_list_and_undo(api, tmp_path):
    path = workbook(tmp_path, [inst(1), inst(2, region="Narnia")], [fact(1, "T-INST-001")])
    v = api.post(BASE + "/validate", data={"country": COUNTRY}, files=upload(path), headers=ADMIN).json()
    assert v["counts"]["Institutions"]["rejected"] == 1
    assert [r["reason"] for r in v["rows"] if r["sheet"] == "Institutions"] == ["unknown_region"]
    assert api.get(BASE, headers=ADMIN).json() == {"imports": []}  # a dry run logs nothing
    r = api.post(BASE, data=FORM, files=upload(path), headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["Facts"]["verified"] == 1 and "unknown_region" in body["report_csv"]
    iid = body["import_id"]
    assert api.post(BASE, data=FORM, files=upload(path), headers=ADMIN).status_code == 409
    one = api.get(f"{BASE}/{iid}", headers=ADMIN).json()
    # the actor is the identity behind the admin token; the name typed in the form is only a note beside it
    assert (one["status"], one["mode"], one["decision_ref"], one["actor"], one["note_actor"]) == (
        "done", "owner_accepted", "chat 2026-11-07", "admin", "dev")
    rep = api.get(f"{BASE}/{iid}/report", headers=ADMIN)  # the report outlives the temp file it was written beside
    assert rep.status_code == 200 and rep.text == body["report_csv"] and "unknown_region" in rep.text
    assert [i["id"] for i in api.get(BASE, headers=ADMIN).json()["imports"]] == [iid]
    u = api.post(f"{BASE}/{iid}/undo", data={"actor": "admin"}, headers=ADMIN)
    assert u.status_code == 200 and u.json() == {"facts": 1, "registry": 1, "programmes": 0, "links": 0}
    assert api.post(f"{BASE}/{iid}/undo", data={"actor": "admin"}, headers=ADMIN).status_code == 409
    assert api.post(f"{BASE}/999/undo", data={"actor": "admin"}, headers=ADMIN).status_code == 404
    assert api.get(f"{BASE}/999", headers=ADMIN).status_code == 404


def test_bad_requests(api, tmp_path):
    path = workbook(tmp_path, [inst(1)])
    both = {**FORM, "reviewers": "true"}
    assert api.post(BASE, data=both, files=upload(path), headers=ADMIN).status_code == 422
    assert api.post(BASE, data={"country": COUNTRY, "actor": "dev"}, files=upload(path), headers=ADMIN).status_code == 422
    wb = openpyxl.Workbook()
    wb.save(tmp_path / "empty.xlsx")
    r = api.post(BASE, data=FORM, files=upload(tmp_path / "empty.xlsx"), headers=ADMIN)
    assert r.status_code == 422 and "Institutions" in r.json()["detail"]
    assert api.get(f"{BASE}/999/report", headers=ADMIN).status_code == 404
    assert api.post(BASE + "/validate", data={"country": "ZZ"}, files=upload(path), headers=ADMIN).status_code == 422
