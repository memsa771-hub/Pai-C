"""Slice 3 Task 8: the documents API (spec §4, S3-D9, S3-D10). Synthetic files only; the reading is simulated by
writing fields through the store, as the os.document workflow would."""

import io
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents.run import document_workflow_id
from app.os.documents.store import DocumentStore, FindingStore
from app.os.documents.types import load_document_types
from app.os.documents.validators import validate
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.test_api import ADMIN, TEST_TERMS, TOKEN, agree, as_student
from tests.os.test_api_knowledge import FakeClient as _FakeClient

FAKE = Path(__file__).parent / "playbooks"


class FakeClient(_FakeClient):
    """Also records the workflows a delete asks DBOS to forget."""

    def __init__(self):
        super().__init__()
        self.deleted: list[str] = []

    def list_workflows(self, *, workflow_id_prefix=None, **_):
        from types import SimpleNamespace

        return [SimpleNamespace(workflow_id=o["workflow_id"]) for o, _ in self.calls
                if o["workflow_id"].startswith(workflow_id_prefix)]

    def cancel_workflows(self, ids):
        pass

    def delete_workflows(self, ids, **_):
        self.deleted.extend(ids)
TYPES = load_document_types()
TENANT = "pai"
# Fictional values only.
TRANSCRIPT = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Khan", "date_of_birth": "2001-04-12",
              "institution": "Example University", "cgpa": 3.7, "cgpa_scale": 4.0}
DEGREE = {"student_name": "Sara Ahmed Khan", "father_name": "Rashid Khan", "institution": "Example University"}


def jpeg(seed: int = 1) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 400), (seed % 256, 120, 120)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    fake = FakeClient()
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: fake,
                             terms_dir=TEST_TERMS)
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.fake, c.engine = fake, engine
    return c


def upload(api, doc_type="transcript", data=None, name="transcript.jpg", student="stu-1"):
    agree(api, student)
    return api.post("/v1/os/documents", data={"doc_type": doc_type},
                    files={"file": (name, data if data is not None else jpeg(), "image/jpeg")},
                    headers=as_student(student))


def simulate_read(engine, doc_id: int, doc_type: str, values: dict, status: str = "read") -> None:
    """What the os.document workflow stores (Task 7), without running it."""
    from datetime import date

    from app.os.documents.checks import load_name_variants
    from app.os.documents.run import compare_documents

    store, t = DocumentStore(engine, TENANT), TYPES[doc_type]
    full = {f.name: values.get(f.name) for f in t.fields}
    store.save_fields(doc_id, full, validate(t, full, date(2026, 10, 21)))
    store.set_status(doc_id, status, detected_type=doc_type, pages=1)
    compare_documents(engine, TENANT, store.get(doc_id).student_ref, TYPES, load_name_variants())


def confirm_body(doc_type: str, values: dict) -> dict:
    return {"fields": {f.name: values.get(f.name) for f in TYPES[doc_type].fields}}


def list_docs(api, student="stu-1") -> dict:
    r = api.get("/v1/os/documents", headers=as_student(student))
    assert r.status_code == 200
    return r.json()


# --- upload ----------------------------------------------------------------------------------------------------


def test_upload_201_and_enqueued(api):
    r = upload(api)
    assert r.status_code == 201
    doc = r.json()
    assert (doc["doc_type"], doc["status"], doc["filename"], doc["fields"]) == \
        ("transcript", "uploaded", "transcript.jpg", [])
    stored = DocumentStore(api.engine, TENANT).get(doc["id"])
    assert stored.content_type == "image/jpeg" and stored.student_ref == "stu-1"
    [(options, args)] = api.fake.calls
    assert options["workflow_name"] == "os.document" and args == (doc["id"],)
    assert options["workflow_id"] == document_workflow_id(TENANT, doc["id"], stored.sha256)


def test_upload_needs_sign_in(api):
    r = api.post("/v1/os/documents", data={"doc_type": "transcript"}, files={"file": ("a.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 401


def test_upload_bad_type_422(api):
    assert upload(api, data=b"hello, not a document", name="fake.pdf").status_code == 422  # magic bytes
    assert upload(api, doc_type="birth_certificate").status_code == 422  # not a configured type
    big = b"\xff\xd8\xff" + b"0" * 10_000_000
    assert upload(api, data=big).status_code == 422  # over 10,000,000 bytes
    assert upload(api, data=b"").status_code == 422
    assert api.fake.calls == []
    with api.engine.connect() as conn:
        assert conn.execute(select(models.documents)).all() == []  # nothing stored


def test_upload_kind_comes_from_bytes(api):
    png = io.BytesIO()
    Image.new("RGB", (50, 50)).save(png, "PNG")
    r = upload(api, data=png.getvalue(), name="scan.jfif")
    assert r.status_code == 201
    assert DocumentStore(api.engine, TENANT).get(r.json()["id"]).content_type == "image/png"


def test_duplicate_per_student_only(api):
    """Review Focus #4: the same file from two students is allowed; twice from one student is 409."""
    data = jpeg(7)
    assert upload(api, data=data, student="stu-1").status_code == 201
    assert upload(api, data=data, student="stu-2").status_code == 201
    r = upload(api, data=data, student="stu-1")
    assert r.status_code == 409 and "already" in r.json()["detail"]
    assert len(api.fake.calls) == 2


# --- reading the documents -------------------------------------------------------------------------------------


def test_list_gives_the_document_types(api):
    """The screens show the configured types and their labels; nothing about a type is written in the frontend."""
    types = list_docs(api)["doc_types"]
    assert {t["key"] for t in types} == set(TYPES)
    assert {"key": "passport", "label": "Passport"} in types
    assert [t["label"] for t in types] == sorted(t["label"] for t in types)


def test_student_sees_only_own(api):
    mine = upload(api, data=jpeg(1), student="stu-1").json()["id"]
    theirs = upload(api, data=jpeg(2), student="stu-2").json()["id"]
    simulate_read(api.engine, mine, "transcript", TRANSCRIPT)
    simulate_read(api.engine, theirs, "transcript", TRANSCRIPT)
    docs = list_docs(api, "stu-1")["documents"]
    assert [d["id"] for d in docs] == [mine]
    by_field = {f["field"]: f for f in docs[0]["fields"]}
    assert by_field["cgpa"] == {"field": "cgpa", "value_read": 3.7, "check": "ok", "reasons": [],
                                "value_confirmed": None, "label": None}  # no plain label: the page words the name
    # another student's document cannot be confirmed, deleted or seen through any write
    body = confirm_body("transcript", TRANSCRIPT)
    assert api.post(f"/v1/os/documents/{theirs}/confirm", json=body, headers=as_student("stu-1")).status_code == 404
    assert api.delete(f"/v1/os/documents/{theirs}", headers=as_student("stu-1")).status_code == 404
    assert DocumentStore(api.engine, TENANT).get(theirs).status == "read"


def test_list_shows_open_findings(api):
    t = upload(api, data=jpeg(1)).json()["id"]
    d = upload(api, doc_type="degree_certificate", data=jpeg(2), name="degree.jpg").json()["id"]
    simulate_read(api.engine, t, "transcript", TRANSCRIPT)
    simulate_read(api.engine, d, "degree_certificate", DEGREE)
    out = list_docs(api)
    [finding] = out["findings"]
    assert (finding["kind"], finding["field"]) == ("mismatch", "father_name")
    assert finding["items"] == [{"document_id": t, "value": "Ahmed Khan"}, {"document_id": d, "value": "Rashid Khan"}]
    assert all([f["id"] for f in doc["findings"]] == [finding["id"]] for doc in out["documents"])


# --- confirming ------------------------------------------------------------------------------------------------


def test_partial_confirm_422(api):
    doc_id = upload(api).json()["id"]
    simulate_read(api.engine, doc_id, "transcript", TRANSCRIPT)
    body = confirm_body("transcript", TRANSCRIPT)
    del body["fields"]["cgpa"]
    r = api.post(f"/v1/os/documents/{doc_id}/confirm", json=body, headers=as_student())
    assert r.status_code == 422 and "cgpa" in r.json()["detail"]
    extra = confirm_body("transcript", TRANSCRIPT)
    extra["fields"]["shoe_size"] = "9"
    assert api.post(f"/v1/os/documents/{doc_id}/confirm", json=extra, headers=as_student()).status_code == 422
    assert DocumentStore(api.engine, TENANT).get(doc_id).status == "read"


def test_confirm_before_read_409(api):
    doc_id = upload(api).json()["id"]
    r = api.post(f"/v1/os/documents/{doc_id}/confirm", json=confirm_body("transcript", TRANSCRIPT),
                 headers=as_student())
    assert r.status_code == 409


def test_confirm_sets_profile_with_source(api):
    doc_id = upload(api).json()["id"]
    simulate_read(api.engine, doc_id, "transcript", TRANSCRIPT)
    corrected = {**TRANSCRIPT, "cgpa": 3.71}  # the student corrects a value
    r = api.post(f"/v1/os/documents/{doc_id}/confirm", json=confirm_body("transcript", corrected),
                 headers=as_student())
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    fields = {f["field"]: f for f in r.json()["fields"]}
    assert fields["cgpa"]["value_read"] == 3.7 and fields["cgpa"]["value_confirmed"] == 3.71  # read value kept
    profile = {p["key"]: p for p in api.get("/v1/os/profile", headers=as_student()).json()["values"]}
    assert profile["full_name"]["value"] == "Sara Ahmed Khan"
    assert profile["date_of_birth"]["value"] == "2001-04-12"
    assert profile["transcript.cgpa"]["value"] == 3.71
    assert all(p["source_document_id"] == doc_id for p in profile.values())  # invariant 3
    assert "transcript.serial_number" not in profile  # an empty value is not a profile value
    assert api.get("/v1/os/profile", headers=as_student("stu-2")).json()["values"] == []


def test_open_finding_holds_back_profile_value(api):
    t = upload(api, data=jpeg(1)).json()["id"]
    d = upload(api, doc_type="degree_certificate", data=jpeg(2), name="degree.jpg").json()["id"]
    simulate_read(api.engine, t, "transcript", TRANSCRIPT)
    simulate_read(api.engine, d, "degree_certificate", DEGREE)
    api.post(f"/v1/os/documents/{t}/confirm", json=confirm_body("transcript", TRANSCRIPT), headers=as_student())
    keys = {p["key"] for p in api.get("/v1/os/profile", headers=as_student()).json()["values"]}
    assert "full_name" in keys and "father_name" not in keys  # an open mismatch covers father_name


def test_confirm_with_correction_rechecks_findings(api):
    t = upload(api, data=jpeg(1)).json()["id"]
    d = upload(api, doc_type="degree_certificate", data=jpeg(2), name="degree.jpg").json()["id"]
    simulate_read(api.engine, t, "transcript", TRANSCRIPT)
    simulate_read(api.engine, d, "degree_certificate", DEGREE)
    assert len(list_docs(api)["findings"]) == 1
    fixed = {**DEGREE, "father_name": "Ahmed Khan"}  # the reading was wrong; the student corrects it
    api.post(f"/v1/os/documents/{d}/confirm", json=confirm_body("degree_certificate", fixed), headers=as_student())
    assert list_docs(api)["findings"] == []


def test_resolve_finding_sets_profile(api):
    t = upload(api, data=jpeg(1)).json()["id"]
    d = upload(api, doc_type="degree_certificate", data=jpeg(2), name="degree.jpg").json()["id"]
    simulate_read(api.engine, t, "transcript", TRANSCRIPT)
    simulate_read(api.engine, d, "degree_certificate", DEGREE)
    [finding] = list_docs(api)["findings"]
    url = f"/v1/os/documents/findings/{finding['id']}/resolve"
    assert api.post(url, json={"value": "Someone Else"}, headers=as_student()).status_code == 422  # not a choice
    assert api.post(url, json={"value": "Ahmed Khan"}, headers=as_student("stu-2")).status_code == 404
    r = api.post(url, json={"value": "Ahmed Khan"}, headers=as_student())
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["resolution"] == "Ahmed Khan"
    profile = {p["key"]: p for p in api.get("/v1/os/profile", headers=as_student()).json()["values"]}
    assert profile["father_name"]["value"] == "Ahmed Khan" and profile["father_name"]["source_document_id"] == t
    assert list_docs(api)["findings"] == []
    # a later re-check does not reopen what the student resolved
    api.post(f"/v1/os/documents/{t}/confirm", json=confirm_body("transcript", TRANSCRIPT), headers=as_student())
    assert list_docs(api)["findings"] == []
    assert api.post(url, json={"value": "Ahmed Khan"}, headers=as_student()).status_code == 409  # already resolved


# --- deleting --------------------------------------------------------------------------------------------------


def test_delete_removes_bytes(api):
    doc_id = upload(api).json()["id"]
    simulate_read(api.engine, doc_id, "transcript", TRANSCRIPT)
    api.post(f"/v1/os/documents/{doc_id}/confirm", json=confirm_body("transcript", TRANSCRIPT), headers=as_student())
    assert api.delete(f"/v1/os/documents/{doc_id}", headers=as_student()).status_code == 204
    assert api.fake.deleted == [api.fake.calls[0][0]["workflow_id"]]  # its reading is forgotten by DBOS too (C1)
    with api.engine.connect() as conn:
        assert conn.execute(select(models.document_files)).all() == []
        assert conn.execute(select(models.document_fields)).all() == []
        row = conn.execute(select(models.documents)).one()
    assert row.status == "deleted" and row.deleted_at is not None  # the audit row stays
    assert list_docs(api)["documents"] == []
    assert api.get("/v1/os/profile", headers=as_student()).json()["values"] == []  # its values go with it
    assert api.delete(f"/v1/os/documents/{doc_id}", headers=as_student()).status_code == 404
    assert upload(api).status_code == 201  # the same file may be uploaded again


def test_delete_clears_findings_it_was_part_of(api):
    t = upload(api, data=jpeg(1)).json()["id"]
    d = upload(api, doc_type="degree_certificate", data=jpeg(2), name="degree.jpg").json()["id"]
    simulate_read(api.engine, t, "transcript", TRANSCRIPT)
    simulate_read(api.engine, d, "degree_certificate", DEGREE)
    api.delete(f"/v1/os/documents/{d}", headers=as_student())
    assert FindingStore(api.engine, TENANT).list_open("stu-1") == []


# --- admin -----------------------------------------------------------------------------------------------------


def test_admin_view_never_returns_bytes(api):
    data = jpeg(3)
    doc_id = upload(api, data=data).json()["id"]
    simulate_read(api.engine, doc_id, "transcript", TRANSCRIPT)
    assert api.get("/v1/os/documents/admin", params={"student": "stu-1"}).status_code == 401
    r = api.get("/v1/os/documents/admin", params={"student": "stu-1"}, headers=ADMIN)
    assert r.status_code == 200
    [doc] = r.json()["documents"]
    assert doc["status"] == "read" and {f["field"] for f in doc["fields"]} >= {"cgpa", "student_name"}
    assert "findings" in r.json()
    body = r.content
    assert data[:64] not in body and b"/9j/" not in body  # neither raw nor base64 JPEG bytes
    assert not ({"data", "file", "bytes", "content"} & set(doc))
    assert api.get("/v1/os/documents/admin", params={"student": "stu-1"}, headers=as_student()).status_code == 401


def test_resolved_value_survives_confirm(api):
    """Review I2: the student resolved a finding; confirming one of its documents unchanged keeps their choice."""
    t = upload(api, data=jpeg(1)).json()["id"]
    d = upload(api, doc_type="degree_certificate", data=jpeg(2), name="degree.jpg").json()["id"]
    simulate_read(api.engine, t, "transcript", TRANSCRIPT)
    simulate_read(api.engine, d, "degree_certificate", {**DEGREE, "student_name": "Sara Ahmad Khan",
                                                          "father_name": "Ahmed Khan"})
    [finding] = list_docs(api)["findings"]
    assert (finding["kind"], finding["field"]) == ("variant", "full_name")
    api.post(f"/v1/os/documents/findings/{finding['id']}/resolve", json={"value": "Sara Ahmed Khan"},
             headers=as_student())
    api.post(f"/v1/os/documents/{d}/confirm",
             json=confirm_body("degree_certificate", {**DEGREE, "student_name": "Sara Ahmad Khan",
                                                      "father_name": "Ahmed Khan"}), headers=as_student())
    profile = {p["key"]: p for p in api.get("/v1/os/profile", headers=as_student()).json()["values"]}
    assert profile["full_name"]["value"] == "Sara Ahmed Khan" and profile["full_name"]["source_document_id"] == t
    assert profile["father_name"]["value"] == "Ahmed Khan"  # no finding on it: set as confirmed


def test_failed_document_can_be_deleted_and_uploaded_again(api):
    """Review I3: a reading that failed is not a dead end. The student deletes it and uploads the file again
    (spec §6: "the student can retry")."""
    data = jpeg(5)
    doc_id = upload(api, data=data).json()["id"]
    DocumentStore(api.engine, TENANT).set_status(doc_id, "failed", error="We could not read this document.")
    assert upload(api, data=data).status_code == 409  # still there
    assert api.delete(f"/v1/os/documents/{doc_id}", headers=as_student()).status_code == 204
    r = upload(api, data=data)
    assert r.status_code == 201 and r.json()["status"] == "uploaded"
