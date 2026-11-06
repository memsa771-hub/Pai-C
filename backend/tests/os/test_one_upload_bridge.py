"""P1-T7 Task 2 (R-01, row 6.7): the one upload entry point against a real PAI OS. The Counsellor side is the real HTTP
API on a student session (SQLite, a temp file store); the OS side is the real services on Postgres behind the real
bridge functions. The OS reader is not run (no model): the fake DBOS client only records the start. Fictional data."""

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import DocumentArtifact, FileRecord
from app.os import models, ports
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents import connect_texts
from app.os.documents.store import DocumentStore
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.one_upload_support import PDF, jobs, post_file, upload_world
from tests.os.test_api import TEST_TERMS, TOKEN
from tests.os.test_api_documents import FakeClient
from tests.os.test_document_run import TRANSCRIPT, documents, stop  # noqa: F401

pytestmark = pytest.mark.req("R-01")

FAKE = __import__("pathlib").Path(__file__).parent / "playbooks"
TENANT = "pai"


@pytest.fixture
def world(engine, clean, os_db, tmp_path, monkeypatch):
    """The OS on the real bridge adapters, the part on, the student on the Counsellor app."""
    fake = FakeClient()
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: fake,
                        terms_dir=TEST_TERMS)
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id=TENANT, enabled=True))
    ports.configure(svc, document_files=bridge.document_file_bytes, documents_enabled=bridge.documents_enabled,
                    on_document_deleted=bridge.on_os_document_deleted)
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", True)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    try:
        with upload_world(tmp_path) as (client, who, auth):
            yield SimpleWorld(client, who, auth, svc, fake, TestClient(app))
    finally:
        ports.configure(None)


class SimpleWorld:
    def __init__(self, client, who, auth, svc, fake, os_client):
        self.client, self.who, self.auth, self.svc, self.fake, self.os = client, who, auth, svc, fake, os_client
        self.id = who.workspace_id

    def agree(self):
        from app.os.consent import ConsentStore, current_terms

        ConsentStore(self.svc.engine, TENANT).agree(self.id, current_terms(self.svc.terms_dir).version)

    def upload(self, name="transcript.pdf", data=PDF, **fields):
        return post_file(self.client, self.who, self.auth, name=name, data=data, **fields)

    def os_rows(self):
        with self.svc.engine.connect() as conn:
            return conn.execute(select(models.documents)).all()

    def count(self, table) -> int:
        with self.svc.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar()

    def records(self):
        with self.who.factory() as db:
            return db.scalars(select(FileRecord)).all()

    def typed(self):
        self.agree()
        got = self.upload(doc_type="transcript")
        assert got.status_code == 200, got.text
        return got.json()["data"]


def test_typed_upload_stores_once_and_registers(world):
    data = world.typed()
    (record,) = world.records()
    assert record.id == data["id"] and record.status == "active"
    (row,) = world.os_rows()
    assert row.file_ref == data["id"] and row.student_ref == world.id and row.doc_type == "transcript"
    assert data["os_document"]["id"] == row.id and data["os_document"]["status"] == "uploaded"
    assert world.count(models.document_files) == 0  # the OS keeps no bytes of its own
    from app.files.storage import get_file_store

    assert get_file_store().read(record.storage_key) == PDF  # one copy, in the Counsellor store
    assert DocumentStore(world.svc.engine, TENANT).file_bytes(row.id) == PDF  # and the OS reads it from there
    assert "extract" in jobs(world.who, "document.parse")[0][1] and jobs(world.who, "document.extract") == []


def test_registration_refusals_keep_the_file(world):
    world.agree()
    first = world.upload(doc_type="transcript").json()["data"]
    again = world.upload(name="again.pdf", doc_type="transcript").json()["data"]  # the same bytes
    assert again["os_document"]["refused"] == "duplicate"
    bad = world.upload(name="notes.pdf", data=b"not a pdf", doc_type="transcript").json()["data"]
    assert bad["os_document"]["refused"] == "not_readable"
    unknown = world.upload(name="x.png", data=b"\x89PNG\r\n\x1a\n" + b"y" * 64, doc_type="no_such_type").json()["data"]
    assert unknown["os_document"]["refused"] == "unknown_type"
    assert len(world.records()) == 4 and len(world.os_rows()) == 1 and first["os_document"]["id"]


def test_consent_is_asked_before_registration(world):
    got = world.upload(doc_type="transcript").json()["data"]
    assert got["os_document"]["refused"] == "consent_needed" and got["os_document"]["note"]
    assert len(world.records()) == 1 and world.os_rows() == []


def test_register_later_from_a_chat_attachment(world):
    world.agree()
    file_id = world.upload().json()["data"]["id"]  # no type: today's pipeline
    assert world.os_rows() == [] and jobs(world.who, "document.parse")[0][1].get("extract") is None
    got = world.client.post(f"/v1/uploads/{file_id}/os-document", params={"network": world.id}, headers=world.auth,
                            json={"doc_type": "transcript"})
    assert got.status_code == 200 and got.json()["data"]["os_document"]["status"] == "uploaded"
    (row,) = world.os_rows()
    assert row.file_ref == file_id


def test_options_lists_the_os_types(world):
    got = world.client.get("/v1/uploads/options", params={"network": world.id}, headers=world.auth).json()["data"]
    keys = [t["key"] for t in got["doc_types"]]
    assert got["one_upload"] is True and "transcript" in keys and keys == sorted(keys)
    assert all(t["label"] for t in got["doc_types"])


def test_adapter_refuses_other_students_and_trashed_files(world):
    data = world.typed()
    file_id = data["id"]
    assert bridge.document_file_bytes(world.id, file_id) == PDF
    for student, ref in ((world.id + "-other", file_id), ("someone-else", file_id), (world.id, "no-such-file"),
                         (world.id, "")):
        with pytest.raises(KeyError):
            bridge.document_file_bytes(student, ref)
    assert world.client.delete(f"/v1/files/{file_id}", headers=world.auth).status_code == 200  # trashed
    with pytest.raises(KeyError):
        bridge.document_file_bytes(world.id, file_id)


def test_adapter_refuses_a_file_of_another_workspace(world):
    from app.models import Workspace

    world.typed()
    with world.who.factory() as db:
        other = Workspace(name="Other student")
        db.add(other)
        db.flush()
        db.add(FileRecord(id="00000000-0000-4000-8000-0000000000aa", workspace_id=str(other.id), filename="o.pdf",
                          content_type="application/pdf", size=1, storage_key="elsewhere", uploaded_by="human:x"))
        db.commit()
        other_id = str(other.id)
    with pytest.raises(KeyError):
        bridge.document_file_bytes(world.id, "00000000-0000-4000-8000-0000000000aa")  # exists, but is not theirs
    with pytest.raises(KeyError):
        bridge.document_file_bytes(other_id, world.records()[0].id)


def test_counsellor_trash_forgets_the_os_document(world):
    data = world.typed()
    (row,) = world.os_rows()
    store = DocumentStore(world.svc.engine, TENANT)
    store.save_fields(row.id, TRANSCRIPT, {})
    assert store.fields(row.id)
    got = world.client.post("/v1/files/trash", headers=world.auth,
                            json={"network": world.id, "file_ids": [data["id"]]})
    assert got.status_code == 200 and got.json()["data"]["trashed_count"] == 1
    assert world.records()[0].status == "deleted" and world.records()[0].trash_id  # in the trash, restorable
    assert store.get(row.id).status == "deleted" and store.fields(row.id) == []
    trash_id = world.records()[0].trash_id
    restored = world.client.post("/v1/files/trash/restore", headers=world.auth,
                                 json={"network": world.id, "trash_ids": [trash_id]})
    assert restored.status_code == 200 and world.records()[0].status == "active"
    assert store.get(row.id).status == "deleted"  # restoring the file does not bring the OS document back
    with pytest.raises(KeyError):
        store.file_bytes(row.id)


def test_counsellor_delete_forgets_the_os_document(world):
    data = world.typed()
    (row,) = world.os_rows()
    assert world.client.delete(f"/v1/files/{data['id']}", headers=world.auth).status_code == 200
    assert DocumentStore(world.svc.engine, TENANT).get(row.id).status == "deleted"
    assert world.records()[0].status == "deleted"  # the file is not purged by this path


def test_os_delete_purges_the_counsellor_file(world):
    data = world.typed()
    file_id = data["id"]
    (record,) = world.records()
    from app.files.storage import get_file_store

    assert get_file_store().exists(record.storage_key)
    with world.who.factory() as db:  # derived document state exists for the file
        assert db.scalars(select(DocumentArtifact).where(DocumentArtifact.file_id == file_id)).all()
    doc_id = data["os_document"]["id"]
    gone = world.os.delete(f"/v1/os/documents/{doc_id}", headers={"x-test-student": world.id})
    assert gone.status_code == 204
    assert world.records() == [] and not get_file_store().exists(record.storage_key)
    with world.who.factory() as db:
        assert db.scalars(select(DocumentArtifact)).all() == []
    assert [p["file_ids"] for _, p in jobs(world.who, "document.unindex")] == [[file_id]]
    assert DocumentStore(world.svc.engine, TENANT).get(doc_id).status == "deleted"
    bridge.on_os_document_deleted(world.id, file_id)  # a second call is a no-op
    bridge.on_os_document_deleted("someone-else", file_id)


def test_os_delete_never_purges_another_students_file(world):
    data = world.typed()
    bridge.on_os_document_deleted("someone-else", data["id"])
    assert len(world.records()) == 1


def test_a_purge_that_raises_leaves_the_file_and_the_os_document_deleted(world, monkeypatch):
    data = world.typed()
    from app.files.storage import get_file_store

    store = get_file_store()

    def broken(key):
        raise OSError("disk")

    doc_id = data["os_document"]["id"]
    with monkeypatch.context() as m:
        m.setattr(store, "delete", broken)
        gone = world.os.delete(f"/v1/os/documents/{doc_id}", headers={"x-test-student": world.id})
    assert gone.status_code == 204  # the student's delete holds; the host failure is swallowed and logged
    assert DocumentStore(world.svc.engine, TENANT).get(doc_id).status == "deleted"
    assert len(world.records()) == 1 and world.records()[0].status == "active"
    bridge.on_os_document_deleted(world.id, data["id"])  # the retry finishes the purge
    assert world.records() == []


def test_os_upload_route_answers_409_while_on(world):
    headers = {"x-test-student": world.id}
    files = {"file": ("t.pdf", PDF, "application/pdf")}
    first = world.os.post("/v1/os/documents", headers=headers, files=files, data={"doc_type": "transcript"})
    assert first.status_code == 409 and first.json()["detail"]["code"] == "consent_needed"  # consent is asked first
    world.agree()
    second = world.os.post("/v1/os/documents", headers=headers, files=files, data={"doc_type": "transcript"})
    assert second.status_code == 409 and second.json()["detail"] == connect_texts.text("use_documents_page")
    assert world.os_rows() == []


def test_off_the_os_route_is_todays(world, monkeypatch):
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", False)
    world.agree()
    got = world.os.post("/v1/os/documents", headers={"x-test-student": world.id}, data={"doc_type": "transcript"},
                        files={"file": ("t.pdf", PDF, "application/pdf")})
    assert got.status_code == 201 and world.count(models.document_files) == 1
    assert world.os_rows()[0].file_ref is None
