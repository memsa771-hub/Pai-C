"""P1-T7 Task 2 (R-01, row 6.7): the one upload entry point on the Counsellor side. A signed-in student on the real app
(SQLite); the PAI OS side is a stand-in behind the bridge functions (the real OS is in tests/os/test_one_upload_bridge.py).
Fictional data only; no model call."""

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import FileRecord, Workspace
from app.pai_c.connect import uploads
from tests.one_upload_support import (PDF, jobs, post_file, post_folder, run_parse_job, upload_world)

pytestmark = pytest.mark.req("R-01")


class Os:
    """A stand-in for PAI OS: records what the bridge was asked and answers as told."""

    def __init__(self):
        self.answer = {"id": 7, "status": "uploaded"}
        self.registered = []
        self.forgotten = []
        self.forget_error = None

    def register(self, student_ref, doc_type, file_ref, filename, data):
        self.registered.append((student_ref, doc_type, file_ref, filename, data))
        return self.answer

    def forget(self, workspace_id, file_id):
        if self.forget_error:
            raise self.forget_error
        self.forgotten.append((workspace_id, file_id))
        return True


@pytest.fixture
def os_on(monkeypatch):
    os = Os()
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", True)
    monkeypatch.setattr(bridge, "counsellor_module_on", lambda: True)
    monkeypatch.setattr(bridge, "register_os_document", os.register)
    monkeypatch.setattr(bridge, "forget_os_document", os.forget)
    monkeypatch.setattr(bridge, "document_types", lambda: [{"key": "transcript", "label": "Transcript"}])
    return os


@pytest.fixture
def world(tmp_path):
    with upload_world(tmp_path) as w:
        yield w


def files(student):
    with student.factory() as db:
        return db.scalars(select(FileRecord)).all()


def parse_payloads(student):
    return [p for _, p in jobs(student, "document.parse")]


def test_typed_upload_stores_once_and_registers(world, os_on):
    client, student, auth = world
    got = post_file(client, student, auth, doc_type="transcript")
    assert got.status_code == 200, got.text
    data = got.json()["data"]
    assert data["os_document"] == {"id": 7, "status": "uploaded", "note": uploads.text("registered")}
    records = files(student)
    assert len(records) == 1 and records[0].id == data["id"]
    from app.files.storage import get_file_store

    assert get_file_store().read(records[0].storage_key) == PDF
    assert os_on.registered == [(student.workspace_id, "transcript", data["id"], records[0].filename, PDF)]


def test_typed_folder_upload_registers_too(world, os_on):
    client, student, auth = world
    got = post_folder(client, student, auth, doc_type="transcript")
    item = got.json()["data"]["files"][0]
    assert item["os_document"]["id"] == 7 and os_on.registered[0][2] == item["id"]
    assert parse_payloads(student)[0].get("extract") is False


def test_typed_upload_skips_counsellor_extraction(world, os_on, monkeypatch):
    client, student, auth = world
    monkeypatch.setattr(config, "PAI_SEMANTIC_RECALL_ENABLED", True)
    file_id = post_file(client, student, auth, doc_type="transcript").json()["data"]["id"]
    assert parse_payloads(student)[0]["extract"] is False
    assert run_parse_job(student, file_id)["parsed"] is True
    assert jobs(student, "document.extract") == []
    assert [p["file_id"] for _, p in jobs(student, "document.index")] == [file_id]  # chat still reads the file


def test_typed_upload_without_recall_queues_no_index(world, os_on, monkeypatch):
    client, student, auth = world
    monkeypatch.setattr(config, "PAI_SEMANTIC_RECALL_ENABLED", False)
    file_id = post_file(client, student, auth, doc_type="transcript").json()["data"]["id"]
    run_parse_job(student, file_id)
    assert jobs(student, "document.extract") == [] and jobs(student, "document.index") == []


def test_untyped_upload_runs_todays_pipeline_even_when_on(world, os_on):
    client, student, auth = world
    got = post_file(client, student, auth)
    assert "os_document" not in got.json()["data"] and os_on.registered == []
    file_id = got.json()["data"]["id"]
    assert "extract" not in parse_payloads(student)[0]
    run_parse_job(student, file_id)
    assert [p for _, p in jobs(student, "document.extract")] == [{"file_id": file_id}]


@pytest.mark.parametrize("code", ["consent_needed", "duplicate", "not_readable", "unknown_type"])
def test_refused_registration_keeps_the_file(world, os_on, code):
    client, student, auth = world
    os_on.answer = {"refused": code}
    got = post_file(client, student, auth, doc_type="transcript")
    assert got.status_code == 200
    assert got.json()["data"]["os_document"] == {"refused": code, "note": uploads.text(code)}
    assert len(files(student)) == 1
    assert "extract" not in parse_payloads(student)[0]  # nothing else reads it, so today's pipeline does


@pytest.mark.parametrize("code", ["terms_not_set", "not_on"])
def test_other_refusals_share_one_plain_sentence(world, os_on, code):
    client, student, auth = world
    os_on.answer = {"refused": code}
    got = post_file(client, student, auth, doc_type="transcript")
    assert got.json()["data"]["os_document"] == {"refused": code, "note": "Saved. PAI cannot read it right now."}


def test_a_failing_registration_never_fails_the_upload(world, os_on, monkeypatch):
    client, student, auth = world

    def boom(*a):
        raise RuntimeError("secret student text")

    monkeypatch.setattr(bridge, "register_os_document", boom)
    got = post_file(client, student, auth, doc_type="transcript")
    assert got.status_code == 200 and got.json()["data"]["os_document"] == {"refused": "failed", "note": uploads.text("not_now")}
    assert len(files(student)) == 1 and "extract" not in parse_payloads(student)[0]


def test_an_agent_upload_is_never_typed(world, os_on):
    from app.security.event_identity import mint_internal_actor

    client, student, auth = world
    agent = {"X-Workspace-Token": "synthetic-test-only", "X-Internal-Actor": mint_internal_actor("openagents:someone")}
    got = client.post("/v1/files", headers=agent, data={"network": student.workspace_id, "doc_type": "transcript"},
                      files={"file": ("a.pdf", PDF, "application/pdf")})
    assert got.status_code == 200, got.text
    assert got.json()["data"]["uploaded_by"] == "openagents:someone"
    assert "os_document" not in got.json()["data"] and os_on.registered == []
    assert "extract" not in parse_payloads(student)[0]


def test_register_later_from_a_chat_attachment(world, os_on):
    client, student, auth = world
    file_id = post_file(client, student, auth).json()["data"]["id"]
    params = {"network": student.workspace_id}
    got = client.post(f"/v1/uploads/{file_id}/os-document", params=params, headers=auth, json={"doc_type": "transcript"})
    assert got.status_code == 200, got.text
    assert got.json()["data"]["os_document"]["id"] == 7
    assert os_on.registered == [(student.workspace_id, "transcript", file_id, files(student)[0].filename, PDF)]
    # another workspace's file is not found, not refused
    with student.factory() as db:
        other = db.scalar(select(Workspace).where(Workspace.id != student.workspace_id))
        db.add(FileRecord(id="00000000-0000-4000-8000-000000000001", workspace_id=str(other.id) if other else
                          student.workspace_id, filename="x.pdf", content_type="application/pdf", size=1,
                          storage_key="nowhere", uploaded_by="human:x"))
        db.commit()
    missing = client.post("/v1/uploads/00000000-0000-4000-8000-000000000001/os-document", params=params,
                          headers=auth, json={"doc_type": "transcript"})
    assert missing.status_code == 404
    gone = client.post("/v1/uploads/not-a-file/os-document", params=params, headers=auth,
                       json={"doc_type": "transcript"})
    assert gone.status_code == 404


def test_register_later_refuses_other_workspaces_file(world, os_on):
    client, student, auth = world
    with student.factory() as db:
        other = Workspace(name="Other")
        db.add(other)
        db.flush()
        db.add(FileRecord(id="00000000-0000-4000-8000-000000000002", workspace_id=str(other.id), filename="x.pdf",
                          content_type="application/pdf", size=1, storage_key="nowhere", uploaded_by="human:x"))
        db.commit()
    got = client.post("/v1/uploads/00000000-0000-4000-8000-000000000002/os-document",
                      params={"network": student.workspace_id}, headers=auth, json={"doc_type": "transcript"})
    assert got.status_code == 404 and os_on.registered == []


def test_register_later_needs_the_part_and_the_student(world, os_on, monkeypatch):
    client, student, auth = world
    file_id = post_file(client, student, auth).json()["data"]["id"]
    params = {"network": student.workspace_id}
    url = f"/v1/uploads/{file_id}/os-document"
    token_only = {"X-Workspace-Token": "synthetic-test-only"}  # a machine credential is not the student
    assert client.post(url, params=params, headers=token_only, json={"doc_type": "t"}).status_code == 403
    assert client.post(url, params=params, json={"doc_type": "t"}).status_code == 401
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", False)
    off = client.post(url, params=params, headers=auth, json={"doc_type": "transcript"})
    assert off.status_code == 409 and os_on.registered == []


def test_options_off_and_on(world, os_on, monkeypatch):
    client, student, auth = world
    params = {"network": student.workspace_id}
    on = client.get("/v1/uploads/options", params=params, headers=auth)
    data = on.json()["data"]
    assert data["one_upload"] is True and data["doc_types"] == [{"key": "transcript", "label": "Transcript"}]
    assert data["text"] == {k: uploads.text(k) for k in uploads.KEYS}
    assert data["text"]["type_label"] == "What is this document?"
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", False)
    assert client.get("/v1/uploads/options", params=params, headers=auth).json()["data"] == {"one_upload": False}
    monkeypatch.setattr(bridge, "counsellor_module_on", lambda: False)  # the flag alone is not enough
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", True)
    assert client.get("/v1/uploads/options", params=params, headers=auth).json()["data"] == {"one_upload": False}
    assert client.get("/v1/uploads/options", params=params).status_code == 401


def test_the_sentences_are_approved_data():
    assert uploads.text("registered") == "Saved. PAI will read it and ask you to check what it found."
    assert uploads.text("type_none") == "Something else"


# --- deleting in the Counsellor forgets the OS document ----------------------------------------------------------


def test_delete_and_trash_tell_the_os_after_the_commit(world, os_on):
    client, student, auth = world
    one = post_file(client, student, auth, name="one.pdf").json()["data"]["id"]
    two = post_file(client, student, auth, name="two.pdf").json()["data"]["id"]
    assert client.delete(f"/v1/files/{one}", headers=auth).status_code == 200
    assert os_on.forgotten == [(student.workspace_id, one)]
    got = client.post("/v1/files/trash", headers=auth, json={"network": student.workspace_id, "file_ids": [two]})
    assert got.status_code == 200 and os_on.forgotten[-1] == (student.workspace_id, two)
    assert {r.status for r in files(student)} == {"deleted"}


def test_a_failing_forget_never_fails_the_delete(world, os_on):
    client, student, auth = world
    os_on.forget_error = RuntimeError("boom")
    one = post_file(client, student, auth).json()["data"]["id"]
    assert client.delete(f"/v1/files/{one}", headers=auth).status_code == 200
    two = post_file(client, student, auth, name="two.pdf").json()["data"]["id"]
    got = client.post("/v1/files/trash", headers=auth, json={"network": student.workspace_id, "file_ids": [two]})
    assert got.status_code == 200 and got.json()["data"]["trashed_count"] == 1
    assert {r.status for r in files(student)} == {"deleted"}


def test_nothing_is_forgotten_for_a_file_that_was_not_found(world, os_on):
    client, student, auth = world
    got = client.post("/v1/files/trash", headers=auth,
                      json={"network": student.workspace_id, "file_ids": ["no-such-file"]})
    assert got.json()["data"]["not_found"] == ["no-such-file"] and os_on.forgotten == []


def test_off_means_the_os_is_not_told_of_a_delete(world, monkeypatch):
    client, student, auth = world

    def boom(*a):
        raise AssertionError("the OS was told")

    monkeypatch.setattr(bridge, "forget_os_document", boom)
    one = post_file(client, student, auth).json()["data"]["id"]
    assert client.delete(f"/v1/files/{one}", headers=auth).status_code == 200


def test_deleting_a_folder_forgets_the_os_documents_in_it(world, os_on):
    client, student, auth = world
    one = post_folder(client, student, auth, name="one.pdf", path="docs").json()["data"]["files"][0]["id"]
    two = post_folder(client, student, auth, name="two.pdf", path="docs").json()["data"]["files"][0]["id"]
    got = client.delete("/v1/files/folders", headers=auth, params={"network": student.workspace_id, "path": "docs"})
    assert got.status_code == 200 and got.json()["data"]["deleted"] == 2
    assert sorted(f for _, f in os_on.forgotten) == sorted([one, two])
    assert {r.status for r in files(student)} == {"deleted"}


def test_replacing_a_file_forgets_the_old_os_document_before_registering_the_new_one(world, os_on, monkeypatch):
    client, student, auth = world
    order = []
    first = post_folder(client, student, auth, name="a.pdf", doc_type="transcript").json()["data"]["files"][0]["id"]
    os_on.forgotten.clear()
    real_forget, real_register = os_on.forget, os_on.register
    monkeypatch.setattr(bridge, "forget_os_document", lambda w, f: (order.append(("forget", f)), real_forget(w, f))[1])
    monkeypatch.setattr(bridge, "register_os_document", lambda *a: (order.append(("register", a[2])), real_register(*a))[1])
    second = post_folder(client, student, auth, name="a.pdf", doc_type="transcript",
                         on_conflict="replace").json()["data"]["files"][0]
    assert second["replaced"] is True and second["os_document"]["id"] == 7
    assert order == [("forget", first), ("register", second["id"])]
    assert {r.id: r.status for r in files(student)} == {first: "deleted", second["id"]: "active"}


def test_a_replace_with_the_part_off_forgets_nothing(world, monkeypatch):
    client, student, auth = world

    def boom(*a):
        raise AssertionError("the OS was told")

    monkeypatch.setattr(bridge, "forget_os_document", boom)
    post_folder(client, student, auth, name="a.pdf")
    got = post_folder(client, student, auth, name="a.pdf", on_conflict="replace")
    assert got.json()["data"]["files"][0]["replaced"] is True


def test_delete_is_committed_before_the_os_is_told(world, os_on):
    client, student, auth = world
    one = post_file(client, student, auth).json()["data"]["id"]
    assert client.delete(f"/v1/files/{one}", headers=auth).status_code == 200
    assert os_on.forgotten == [(student.workspace_id, one)]
    assert {r.status for r in files(student)} == {"deleted"}  # committed before the OS was told


# --- a typed file reports done in the chat context, with today's wording ---------------------------------------


def test_a_typed_file_reaches_the_done_stage_with_todays_wording(world, os_on, monkeypatch):
    from app.documents.progress import STAGE_DONE, document_stage, recent_documents_block
    from app.documents.service import DocumentArtifactService

    client, student, auth = world
    plain = post_file(client, student, auth, name="plain.pdf", data=PDF + b"\n%plain").json()["data"]["id"]
    typed = post_file(client, student, auth, doc_type="transcript").json()["data"]["id"]
    run_parse_job(student, typed)
    with student.factory() as db:
        artifact = DocumentArtifactService(db).get(student.workspace_id, typed)
        assert document_stage(artifact) == STAGE_DONE
        block = recent_documents_block(db, student.workspace_id)
    line = next(l for l in block.splitlines() if typed in l)
    assert "in progress" not in line and "finished — added to the profile: nothing new for the profile" in line
    # a file nobody extracted yet is still "in progress" (today's wording is untouched)
    run_parse_job(student, plain)
    with student.factory() as db:
        assert document_stage(DocumentArtifactService(db).get(student.workspace_id, plain)) != STAGE_DONE
