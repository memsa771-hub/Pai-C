"""P1-T7 Task 1: the DocumentFiles port (P1-D2, D-y1, D-y6, D-y7). Synthetic files only, fictional data, no model."""

import io
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.os import models, ports
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents import connect_texts
from app.os.documents.confirm import delete_document
from app.os.documents.run import document_workflow_id
from app.os.documents.store import DocumentStore
from app.os.playbooks import load_playbook_dir
from app.os.ports import document_files
from app.os.settings import load_settings
from tests.os.test_api import TEST_TERMS, TOKEN, agree, as_student
from tests.os.test_api_documents import FakeClient
from tests.os.test_document_run import STUDENT, TENANT, TRANSCRIPT, documents, jpeg, stop  # noqa: F401

pytestmark = pytest.mark.req("R-01")

FAKE = Path(__file__).parent / "playbooks"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


def png(seed: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + bytes([seed]) * 64


@pytest.fixture(autouse=True)
def reset_port():
    document_files.configure()
    yield
    document_files.configure()
    ports.configure(None)


class Host:
    """A host that keeps files by (student, ref) and records what the OS asks of it."""

    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.reads: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.on = True

    def read(self, student_ref, file_ref):
        self.reads.append((student_ref, file_ref))
        return self.files[(student_ref, file_ref)]

    def enabled(self):
        return self.on

    def on_deleted(self, student_ref, file_ref):
        self.deleted.append((student_ref, file_ref))


@pytest.fixture
def host():
    h = Host()
    document_files.configure(read=h.read, enabled=h.enabled, on_deleted=h.on_deleted)
    return h


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def mounted(engine, clean, os_db, fake):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: fake,
                        terms_dir=TEST_TERMS)
    ports.configure(svc)
    return svc


@pytest.fixture
def api(mounted):
    app = FastAPI()
    app.include_router(build_router(lambda: mounted), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.svc = mounted
    return c


def consent(svc, student="stu-1"):
    from app.os.consent import ConsentStore, current_terms

    ConsentStore(svc.engine, "pai").agree(student, current_terms(svc.terms_dir).version)


# --- the byte change point -----------------------------------------------------------------------------------------


def test_create_ref_stores_no_bytes(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = store.create_ref("stu-1", "transcript", 1, "t.png", "image/png", PNG, "file-1")
    doc = store.get(doc_id)
    import hashlib

    assert doc.file_ref == "file-1" and doc.sha256 == hashlib.sha256(PNG).hexdigest() and doc.size == len(PNG)
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.document_files)).scalar() == 0


def test_file_bytes_reads_through_the_port_with_the_documents_student(engine, clean, host):
    store = DocumentStore(engine, "pai")
    doc_id = store.create_ref("stu-1", "transcript", 1, "t.png", "image/png", PNG, "file-1")
    host.files[("stu-1", "file-1")] = PNG
    assert store.file_bytes(doc_id) == PNG
    assert host.reads == [("stu-1", "file-1")]


def test_file_bytes_without_an_adapter_is_keyerror(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = store.create_ref("stu-1", "transcript", 1, "t.png", "image/png", PNG, "file-1")
    with pytest.raises(KeyError):
        store.file_bytes(doc_id)


def test_file_bytes_other_tenant_is_keyerror(engine, clean, host):
    doc_id = DocumentStore(engine, "pai").create_ref("stu-1", "transcript", 1, "t.png", "image/png", PNG, "file-1")
    host.files[("stu-1", "file-1")] = PNG
    with pytest.raises(KeyError):
        DocumentStore(engine, "other").file_bytes(doc_id)
    assert host.reads == []  # the host is never asked for another tenant's document


def test_file_bytes_standalone_row_reads_os_document_files(engine, clean, host):
    store = DocumentStore(engine, "pai")
    doc_id = store.create("stu-1", "transcript", 1, "t.png", "image/png", PNG)
    assert store.file_bytes(doc_id) == PNG and host.reads == []  # the port is not called


def test_file_bytes_of_a_deleted_linked_document_is_keyerror_and_the_host_is_not_asked(engine, clean, host):
    store = DocumentStore(engine, "pai")
    doc_id = store.create_ref("stu-1", "transcript", 1, "t.png", "image/png", PNG, "file-1")
    host.files[("stu-1", "file-1")] = PNG
    store.delete(doc_id)
    with pytest.raises(KeyError):
        store.file_bytes(doc_id)
    assert host.reads == []


def test_a_host_error_in_read_is_keyerror_without_detail(caplog):
    def boom(student_ref, file_ref):
        raise OSError("disk path /secret")

    document_files.configure(read=boom)
    with pytest.raises(KeyError):
        document_files.read("stu-1", "file-1")
    assert "secret" not in caplog.text and "OSError" in caplog.text


# --- register ------------------------------------------------------------------------------------------------------


def test_register_refusals_in_order(mounted, host):
    svc = mounted
    host.on = False
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-1", "nope", "f1", "t.png", PNG)
    assert e.value.code == "not_on"  # before the type is looked at
    host.on = True
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-1", "nope", "f1", "t.png", PNG)
    assert e.value.code == "unknown_type"
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-1", "transcript", "f1", "t.pdf", b"just text")  # not read before consent
    assert e.value.code == "consent_needed"
    consent(svc)
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-1", "transcript", "f1", "t.pdf", b"just text")
    assert e.value.code == "not_readable"
    out = document_files.register("stu-1", "transcript", "f1", "t.png", PNG)
    assert out["status"] == "uploaded"
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-1", "transcript", "f2", "again.png", PNG)  # the same bytes
    assert e.value.code == "duplicate"
    consent(svc, "stu-2")
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-2", "transcript", "f1", "other.png", png(9))  # the same file ref
    assert e.value.code == "duplicate"


def test_register_terms_not_set(engine, clean, os_db, host, tmp_path):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    folder = tmp_path / "terms"
    folder.mkdir()
    (folder / "pilot.v1.md").write_text("---\nversion: 1\nplaceholder: true\n---\nText.\n", encoding="utf-8")
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: FakeClient(),
                        terms_dir=folder)
    ports.configure(svc)
    document_files.configure(read=host.read, enabled=host.enabled)  # ports.configure resets the port
    with pytest.raises(document_files.Refused) as e:
        document_files.register("stu-1", "transcript", "f1", "t.png", PNG)
    assert e.value.code == "terms_not_set"


def test_register_enqueues_the_document_workflow(mounted, host, fake):
    consent(mounted)
    out = document_files.register("stu-1", "transcript", "f1", "t.png", PNG)
    [(options, args)] = fake.calls
    doc = DocumentStore(mounted.engine, "pai").get(out["id"])
    assert options["workflow_id"] == document_workflow_id("pai", out["id"], doc.sha256)
    assert options["workflow_id"].startswith(f"document:pai:{out['id']}:") and args == (out["id"],)
    assert doc.file_ref == "f1" and doc.student_ref == "stu-1" and doc.filename == "t.png"


def test_register_does_not_take_the_standalone_route(mounted, host):
    consent(mounted)
    document_files.register("stu-1", "transcript", "f1", "t.png", PNG)
    with mounted.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.document_files)).scalar() == 0


# --- the worker reads a registered document ------------------------------------------------------------------------


def test_worker_reads_a_registered_document(documents, host):
    data = jpeg(3)
    doc_id = documents.docs.create_ref(STUDENT, "transcript", 1, "t.jpg", "image/jpeg", data, "file-9")
    host.files[(STUDENT, "file-9")] = data
    documents.read(doc_id)
    doc = documents.docs.get(doc_id)
    assert doc.status in ("read", "needs_student")
    fields = {f["field"]: f["value_read"] for f in documents.docs.fields(doc_id)}
    assert fields["cgpa"] == TRANSCRIPT["cgpa"]
    assert host.reads == [(STUDENT, "file-9")] * 2  # check_file and the reading, once each


# --- forget and the delete hook ------------------------------------------------------------------------------------


def test_forget_deletes_the_linked_document_only(mounted, host):
    consent(mounted)
    consent(mounted, "stu-2")
    a = document_files.register("stu-1", "transcript", "ref-1", "a.png", png(1))["id"]
    b = document_files.register("stu-2", "transcript", "ref-1b", "b.png", png(2))["id"]
    store = DocumentStore(mounted.engine, "pai")
    assert document_files.forget("stu-2", "ref-1") is False  # another student's ref: nothing happens
    assert store.get(a).status == "uploaded"
    assert document_files.forget("stu-1", "ref-1") is True
    assert store.get(a).status == "deleted" and store.get(b).status == "uploaded"
    assert host.deleted == []  # a delete that came from the host is not reported back
    assert document_files.forget("stu-1", "ref-1") is False  # already gone


def test_os_delete_calls_on_deleted_after_the_delete(mounted, host):
    consent(mounted)
    doc_id = document_files.register("stu-1", "transcript", "ref-1", "a.png", png(1))["id"]
    store = DocumentStore(mounted.engine, "pai")
    seen = []
    document_files.configure(read=host.read, enabled=host.enabled,
                             on_deleted=lambda s, r: seen.append((s, r, store.get(doc_id).status)))
    delete_document(mounted.engine, "pai", mounted.document_types, mounted.name_variants, store.get(doc_id),
                    client=mounted.dbos_client())
    assert seen == [("stu-1", "ref-1", "deleted")]


def test_a_failing_hook_still_leaves_the_delete_done(mounted, host):
    consent(mounted)
    doc_id = document_files.register("stu-1", "transcript", "ref-1", "a.png", png(1))["id"]
    store = DocumentStore(mounted.engine, "pai")

    def boom(student_ref, file_ref):
        raise RuntimeError("secret detail")

    document_files.configure(read=host.read, enabled=host.enabled, on_deleted=boom)
    delete_document(mounted.engine, "pai", mounted.document_types, mounted.name_variants, store.get(doc_id),
                    client=mounted.dbos_client())
    assert store.get(doc_id).status == "deleted"


def test_a_standalone_delete_does_not_call_the_hook(mounted, host):
    doc_id = DocumentStore(mounted.engine, "pai").create("stu-1", "transcript", 1, "t.png", "image/png", PNG)
    store = DocumentStore(mounted.engine, "pai")
    delete_document(mounted.engine, "pai", mounted.document_types, mounted.name_variants, store.get(doc_id),
                    client=mounted.dbos_client())
    assert host.deleted == []


# --- the route ------------------------------------------------------------------------------------------------------


def upload(api, student="stu-1", data=None):
    agree(api, student)
    return api.post("/v1/os/documents", data={"doc_type": "transcript"},
                    files={"file": ("t.jpg", data if data is not None else jpeg(1), "image/jpeg")},
                    headers=as_student(student))


def test_upload_route_refuses_while_enabled(api, host, fake):
    r = upload(api)
    assert r.status_code == 409 and r.json() == {"detail": connect_texts.text("use_documents_page")}
    assert connect_texts.text("use_documents_page") == "Upload your documents from the Documents page."
    assert fake.calls == []
    with api.svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.documents)).scalar() == 0


def test_unconfigured_port_upload_is_todays_route(api):
    data = jpeg(2)
    r = upload(api, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "file_ref" not in body and body["status"] == "uploaded"
    with api.svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.document_files)).scalar() == 1
        assert conn.execute(select(models.documents.c.file_ref)).scalar() is None


def test_a_port_that_is_configured_but_off_is_todays_route(api, host):
    host.on = False
    assert upload(api).status_code == 201


def test_a_failing_gate_means_off(host):
    def boom():
        raise RuntimeError("x")

    document_files.configure(read=host.read, enabled=boom)
    assert document_files.enabled() is False


# --- loading ------------------------------------------------------------------------------------------------------


def test_load_names_the_setting_and_never_a_value():
    for spec in ("", "nocolon", "no.such.module:thing", "os:nothing_here", "os:sep"):
        with pytest.raises(document_files.DocumentFilesSourceError, match="OS_DOCUMENT_FILES") as e:
            document_files.load(spec)
        assert spec not in str(e.value) or spec == ""
    import json

    assert document_files.load("json:dumps") is json.dumps


def test_worker_refuses_to_start_with_a_bad_os_document_files(os_db, monkeypatch, capsys):
    from app.os.runner import worker

    monkeypatch.setenv("OS_DATABASE_URL", os_db)
    monkeypatch.setenv("OS_WORKER_ID", "w-test")
    monkeypatch.setenv("OS_DOCUMENT_FILES", "no.such.module:thing")
    assert worker.main([]) == 2
    assert "OS_DOCUMENT_FILES" in capsys.readouterr().err


def test_ports_configure_resets_the_document_files_port(mounted, host):
    ports.configure(None)
    assert document_files.enabled() is False and document_files.current() is None
