"""P2-T5: the review API. Reviewers use their own token; the admin token opens items (P2-D15). Fictional values."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.os import models
from app.os.api import build_router, make_services
from app.os.api.review import REVIEWER_HEADER
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.review import ReviewerStore, load_policy
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.test_api import ADMIN, TOKEN

FAKE = Path(__file__).parent / "playbooks"
AT = datetime(2026, 10, 22, tzinfo=timezone.utc)
URL, QUOTE = "https://uni.test/apply", "Apply by 15 July 2027"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
PAGE = "Admissions\nApply by 15 July 2027 through the portal.\nContact us."
pytestmark = [pytest.mark.req("R-42"), pytest.mark.req("R-25")]


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: None)
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    c = TestClient(app)
    store = ReviewerStore(engine, "pai")
    c.tokens = {}
    for ref, role, kind, ident in (("ai_check_1", "checker", "ai", "model-a"), ("ai_check_2", "approver", "ai", "model-b"),
                                   ("amina", "checker", "person", None), ("owner", "admin", "person", None)):
        c.tokens[ref] = {REVIEWER_HEADER: store.add(ref, ref, role, kind, identity=ident)[1]}
    c.kb = SqlKnowledge(engine, "pai")
    c.fact = c.kb.upsert("programme", "p1", "deadline_close",
                         Fact({"date": "2027-07-15", "tz": "Europe/Berlin"}, QUOTE, URL, AT, 2027, "confirmed"))
    with engine.begin() as conn:
        conn.execute(insert(models.pages).values(tenant_id="pai", url=URL, text=PAGE, http_status=200))
    return c


def open_verify(api) -> int:
    r = api.post("/v1/os/admin/review/items", headers=ADMIN, json={
        "kind": "verify", "dedupe_key": f"verify:{api.fact}", "fact_id": api.fact})
    assert r.status_code == 201, r.text
    return r.json()["item_id"]


def test_reviewer_endpoints_need_a_reviewer_token_not_the_admin_token(api):
    for headers in ({}, ADMIN, {REVIEWER_HEADER: "rvt_nope"}, {REVIEWER_HEADER: ""}):
        assert api.get("/v1/os/review/items", headers=headers).status_code == 401
    assert api.get("/v1/os/review/me", headers=api.tokens["amina"]).json() == {
        "ref": "amina", "display_name": "amina", "identity": "amina", "role": "checker", "kind": "person",
        "active": True}
    # and the admin endpoints do not take a reviewer token
    assert api.post("/v1/os/admin/review/sync", headers=api.tokens["owner"], json={}).status_code == 401
    assert api.get("/v1/os/admin/review/reviewers", headers=api.tokens["owner"]).status_code == 401


def test_a_disabled_reviewer_is_refused(api, engine):
    ReviewerStore(engine, "pai").set_active("amina", False)
    assert api.get("/v1/os/review/me", headers=api.tokens["amina"]).status_code == 401


def test_admin_syncs_the_queue_and_lists_reviewers(api):
    assert api.post("/v1/os/admin/review/sync", headers=ADMIN, json={}).json() == {"opened": 1}
    assert api.post("/v1/os/admin/review/sync", headers=ADMIN, json={}).json() == {"opened": 0}
    refs = [r["ref"] for r in api.get("/v1/os/admin/review/reviewers", headers=ADMIN).json()["reviewers"]]
    assert refs == ["ai_check_1", "ai_check_2", "amina", "owner"]
    bad = api.post("/v1/os/admin/review/items", headers=ADMIN, json={"kind": "verify", "dedupe_key": "x"})
    assert bad.status_code == 422


def test_the_screen_gets_the_fact_the_page_and_the_quote_check(api):
    item = open_verify(api)
    d = api.get(f"/v1/os/review/items/{item}", headers=api.tokens["ai_check_1"]).json()
    assert d["fact"]["status"] == "confirmed" and d["fact"]["high_stakes"] is True
    assert d["fact"]["fact_class"] == "deadline" and d["fact"]["quote"] == QUOTE
    assert d["snapshot"]["text"] == PAGE and d["snapshot"]["quote_found"] is True
    assert d["reviews"] == [] and d["my_review"] is None
    listed = api.get("/v1/os/review/items?kind=verify", headers=api.tokens["amina"]).json()["items"]
    assert [i["id"] for i in listed] == [item]
    assert api.get("/v1/os/review/items?kind=nope", headers=api.tokens["amina"]).status_code == 422
    assert api.get("/v1/os/review/items/999", headers=api.tokens["amina"]).status_code == 404


def test_two_independent_ai_checks_verify_a_fact_and_check_2_is_blind(api):
    item = open_verify(api)
    r1 = api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["ai_check_1"],
                  json={"step": "check", "outcome": "correct", "note": "quote is on the page"})
    assert r1.json()["fact_status"] == "confirmed"
    blind = api.get(f"/v1/os/review/items/{item}", headers=api.tokens["ai_check_2"]).json()
    assert blind["reviews"] == [] and "quote is on the page" not in str(blind)
    again = api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["ai_check_1"],
                     json={"step": "check", "outcome": "correct"})
    assert again.status_code == 409
    wrong_role = api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["amina"],
                          json={"step": "approve", "outcome": "approve"})
    assert wrong_role.status_code == 403
    r2 = api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["ai_check_2"],
                  json={"step": "approve", "outcome": "approve"})
    assert r2.json() == {"item_id": item, "item_status": "closed", "resolution": "verified", "fact_status": "verified"}
    seen = api.get(f"/v1/os/review/items/{item}", headers=api.tokens["ai_check_2"]).json()
    assert [x["reviewer"] for x in seen["reviews"]] == ["ai_check_1", "ai_check_2"]
    assert api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["owner"],
                    json={"step": "check", "outcome": "correct"}).status_code == 409  # closed


def test_bad_review_bodies_are_422(api):
    item = open_verify(api)
    url = f"/v1/os/review/items/{item}/review"
    h = api.tokens["ai_check_1"]
    assert api.post(url, headers=h, json={"step": "check", "outcome": "approve"}).status_code == 422
    assert api.post(url, headers=h, json={"step": "check", "outcome": "wrong"}).status_code == 422
    assert api.post(url, headers=h, json={"step": "check", "outcome": "correct", "bogus": 1}).status_code == 422
    assert api.post(url, headers=h, json={"step": "check", "outcome": "wrong", "corrected_value": 1}).status_code == 422


def test_collection_with_evidence_over_http(api):
    item = open_verify(api)
    api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["ai_check_1"],
             json={"step": "check", "outcome": "unclear", "note": "blurred"})
    [collect] = api.get("/v1/os/review/items?kind=collect", headers=api.tokens["amina"]).json()["items"]
    body = {"value": {"date": "2027-07-15", "tz": "Europe/Berlin"}, "quote": QUOTE, "url": URL}
    h = api.tokens["amina"]
    assert api.post(f"/v1/os/review/items/{collect['id']}/collect", headers=h, json=body).status_code == 422
    bad = api.post(f"/v1/os/review/items/{collect['id']}/evidence", headers=h,
                   files={"file": ("a.exe", b"MZ", "application/x-msdownload")})
    assert bad.status_code == 422
    up = api.post(f"/v1/os/review/items/{collect['id']}/evidence", headers=h,
                  files={"file": ("scan.png", PNG, "image/png")})
    assert up.status_code == 201
    fid = up.json()["id"]
    done = api.post(f"/v1/os/review/items/{collect['id']}/collect", headers=h, json={**body, "evidence_file_id": fid})
    assert done.status_code == 200 and done.json()["resolution"] == "collected"
    got = api.get(f"/v1/os/review/files/{fid}", headers=h)
    assert got.content == PNG and got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff" and got.headers["content-security-policy"] == "sandbox"
    assert api.get(f"/v1/os/review/files/{fid}").status_code == 401
    assert api.get("/v1/os/review/files/999", headers=h).status_code == 404


def test_active_content_is_refused_and_text_is_a_download(api):
    """C1: HTML and SVG are refused whatever they claim; plain text is served as an attachment with a safe name."""
    item = open_verify(api)
    h = api.tokens["amina"]
    url = f"/v1/os/review/items/{item}/evidence"
    for name, ctype, body in (("p.html", "text/html", b"<script>1</script>"), ("p.svg", "image/svg+xml", b"<svg/>"),
                              ("p.png", "image/png", b"<script>1</script>")):
        assert api.post(url, headers=h, files={"file": (name, body, ctype)}).status_code == 422
    up = api.post(url, headers=h, files={"file": ('n"\r\nx.txt', b"Notice text", "text/plain")})
    assert up.status_code == 201
    got = api.get(f"/v1/os/review/files/{up.json()['id']}", headers=h)
    disp = got.headers["content-disposition"]
    assert disp.startswith("attachment") and "\r" not in disp and "\n" not in disp and "filename*=UTF-8''" in disp
    assert got.headers["x-content-type-options"] == "nosniff"
    pdf = api.post(url, headers=h, files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert api.get(f"/v1/os/review/files/{pdf.json()['id']}", headers=h).headers["content-disposition"].startswith("inline")


def test_the_size_cap_holds_before_and_after_reading(api):
    item = open_verify(api)
    h = api.tokens["amina"]
    big = b"x" * (load_policy().evidence_max_bytes + 1)
    assert api.post(f"/v1/os/review/items/{item}/evidence", headers=h,
                    files={"file": ("big.txt", big, "text/plain")}).status_code == 413


def test_admin_audit_shows_identities_and_reviewers_do_not(api):
    item = open_verify(api)
    api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["ai_check_1"],
             json={"step": "check", "outcome": "correct"})
    admin_reviewer = api.get(f"/v1/os/review/items/{item}", headers=api.tokens["owner"]).json()
    assert admin_reviewer["reviews"] == []  # an admin reviewer has no view into open reviews
    assert api.get(f"/v1/os/admin/review/items/{item}/audit", headers=ADMIN).status_code == 409  # open: refused
    api.post(f"/v1/os/review/items/{item}/review", headers=api.tokens["ai_check_2"],
             json={"step": "approve", "outcome": "approve"})
    audit = api.get(f"/v1/os/admin/review/items/{item}/audit", headers=ADMIN).json()
    assert [(r["reviewer"], r["identity"]) for r in audit["reviews"]] == [
        ("ai_check_1", "model-a"), ("ai_check_2", "model-b")]
    assert api.get(f"/v1/os/admin/review/items/{item}/audit", headers=api.tokens["owner"]).status_code == 401
    assert api.get("/v1/os/admin/review/items/999/audit", headers=ADMIN).status_code == 404


def test_resolve_and_attest_over_http(api):
    r = api.post("/v1/os/admin/review/items", headers=ADMIN, json={
        "kind": "suspect_domain", "dedupe_key": "sd:x.test", "subject": "x.test", "summary": "asks for fees"})
    item = r.json()["item_id"]
    h = api.tokens["amina"]
    out = api.post(f"/v1/os/review/items/{item}/resolve", headers=h, json={"outcome": "dismissed", "note": "mirror"})
    assert out.json()["resolution"] == "dismissed"
    assert api.post(f"/v1/os/review/items/{item}/resolve", headers=h,
                    json={"outcome": "dismissed", "note": "again"}).status_code == 409
    a = api.post("/v1/os/review/batches/b3/attest", headers=h)
    assert a.json() == {"batch_ref": "b3", "reviewer": "amina", "new": True}
    assert api.post("/v1/os/review/batches/b3/attest", headers=h).json()["new"] is False
