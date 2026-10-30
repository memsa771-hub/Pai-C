"""Slice 3 Task 2: document tables (os_0004) and the store (spec §3)."""

import pytest
from sqlalchemy import create_engine, inspect, insert, select

from app.os import models
from app.os.db import OS_SCHEMA
from app.os.documents.store import DocumentStore, DuplicateDocument, FindingStore, ProfileStore

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
OTHER = b"\x89PNG\r\n\x1a\n" + b"y" * 64


def new_doc(store, student="stu-1", data=PNG, doc_type="passport"):
    return store.create(student, doc_type, 1, "scan.png", "image/png", data)


def test_migration_up_down_up(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0003"], os_db)
    eng = create_engine(os_db)
    try:
        tables = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        assert not tables & {"os_documents", "os_document_files", "os_document_fields", "os_document_findings",
                             "os_profile_values"}
        assert "document_id" not in {c["name"] for c in inspect(eng).get_columns("os_agent_runs", schema=OS_SCHEMA)}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_create_and_read_back(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = new_doc(store)
    doc = store.get(doc_id)
    assert (doc.student_ref, doc.doc_type, doc.type_version, doc.status, doc.size) == ("stu-1", "passport", 1,
                                                                                      "uploaded", len(PNG))
    assert len(doc.sha256) == 64 and store.file_bytes(doc_id) == PNG


def test_duplicate_per_student(engine, clean):
    store = DocumentStore(engine, "pai")
    new_doc(store)
    with pytest.raises(DuplicateDocument):
        new_doc(store)
    new_doc(store, student="stu-2")  # another student may upload the same file
    new_doc(store, data=OTHER)


def test_save_fields_idempotent(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = new_doc(store)
    values = {"surname": "KHAN", "date_of_birth": "31/02/2024"}
    checks = {"surname": ("ok", []), "date_of_birth": ("check_failed", ["not a real date"])}
    store.save_fields(doc_id, values, checks)
    store.save_fields(doc_id, values, checks)
    fields = {f["field"]: f for f in store.fields(doc_id)}
    assert len(fields) == 2 and fields["date_of_birth"]["check"] == "check_failed"
    assert fields["date_of_birth"]["value_read"] == "31/02/2024" and fields["date_of_birth"]["reasons"] == ["not a real date"]


def test_set_status_records_reading(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = new_doc(store)
    store.set_status(doc_id, "read", detected_type="passport", pages=1)
    doc = store.get(doc_id)
    assert (doc.status, doc.detected_type, doc.pages) == ("read", "passport", 1) and doc.read_at is not None


def test_confirm_requires_every_field(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = new_doc(store)
    store.save_fields(doc_id, {"surname": "KHAN", "given_names": "SARA"},
                      {"surname": ("ok", []), "given_names": ("ok", [])})
    with pytest.raises(ValueError, match="given_names"):
        store.confirm(doc_id, {"surname": "KHAN"})
    store.confirm(doc_id, {"surname": "KHAN", "given_names": "SARA AHMED"})  # a correction
    fields = {f["field"]: f for f in store.fields(doc_id)}
    assert fields["given_names"]["value_read"] == "SARA" and fields["given_names"]["value_confirmed"] == "SARA AHMED"
    assert fields["given_names"]["confirmed_by"] == "student" and store.get(doc_id).status == "confirmed"


def test_delete_removes_bytes_keeps_row(engine, clean):
    store = DocumentStore(engine, "pai")
    doc_id = new_doc(store)
    store.save_fields(doc_id, {"surname": "KHAN"}, {"surname": ("ok", [])})
    store.delete(doc_id)
    doc = store.get(doc_id)
    assert doc.status == "deleted" and doc.deleted_at is not None and store.fields(doc_id) == []
    with pytest.raises(KeyError):
        store.file_bytes(doc_id)
    assert store.list_for("stu-1") == []
    new_doc(store)  # the same file can be uploaded again after a delete


def test_findings_replace_and_resolve(engine, clean):
    findings = FindingStore(engine, "pai")
    findings.replace_open("stu-1", [{"kind": "variant", "field": "full_name", "items": [[1, "Muhammad Ali"], [2, "Mohammad Ali"]]}])
    findings.replace_open("stu-1", [{"kind": "mismatch", "field": "date_of_birth", "items": [[1, "2000-01-01"], [3, "2000-01-02"]]}])
    [open_one] = findings.list_open("stu-1")
    assert open_one["kind"] == "mismatch" and open_one["items"][1] == [3, "2000-01-02"]
    resolved = findings.resolve(open_one["id"], "2000-01-01")
    assert resolved["field"] == "date_of_birth" and findings.list_open("stu-1") == []


def test_profile_value_names_source(engine, clean):
    store, profile = DocumentStore(engine, "pai"), ProfileStore(engine, "pai")
    doc_id = new_doc(store)
    profile.set("stu-1", "full_name", "Sara Ahmed Khan", doc_id)
    profile.set("stu-1", "full_name", "Sara Ahmed Khan", doc_id)  # upsert
    [row] = profile.all("stu-1")
    assert (row["key"], row["value"], row["source_document_id"]) == ("full_name", "Sara Ahmed Khan", doc_id)


def test_tenant_isolation(engine, clean):
    a, b = DocumentStore(engine, "pai"), DocumentStore(engine, "other")
    doc_id = new_doc(a)
    assert b.get(doc_id) is None and b.list_for("stu-1") == []
    with pytest.raises(KeyError):
        b.file_bytes(doc_id)


def test_agent_run_can_belong_to_a_document(engine, clean):
    doc_id = new_doc(DocumentStore(engine, "pai"))
    with engine.begin() as conn:
        conn.execute(insert(models.agent_runs).values(tenant_id="pai", document_id=doc_id, reading="document",
                                                      agent="documents", agent_version=1, model="m"))
    with engine.connect() as conn:
        row = conn.execute(select(models.agent_runs)).one()
    assert row.document_id == doc_id and row.research_run_id is None
