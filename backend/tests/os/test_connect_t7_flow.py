"""P1-T7 Task 6 (R-16, R-01; row 6.7): the whole one-upload flow against a real PAI OS. The Counsellor side is the real
HTTP API on a student session (SQLite, a temp file store); the OS side is the real services behind the ports on
Postgres. The Germany master route is the real playbook, the Pakistan intermediate route is the fake one. The reader
is the OS offline reader on the committed sample documents (no model, no cost): the DBOS worker runs in this process
and reads the file through the host adapter. The reconcile job is run inline (the reconciler on each candidate).
Fictional students; the mailer is stubbed; no chat message is created at any step."""

import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

from app import pai_os_bridge as bridge
from app.config import config
from app.files import storage
from app.memory.reconciler import MemoryReconciler
from app.models import FileRecord, MemoryCandidate, ProfileIssue, User, Workspace
from app.os import models, ports
from app.os.api import build_router, current_student_ref, current_student_ref_for_write
from app.os.documents.store import DocumentStore, ProfileStore
from app.os.eligibility.notes import profile_of
from app.os.ports import document_files, fact_proposals
from tests.auth_fakes import firebase_tokens, identity_for, link_owner
from tests.one_upload_support import PDF, jobs, post_file, run_parse_job
from tests.os.test_api import TEST_TERMS
from tests.os.test_api_documents import TRANSCRIPT, FakeClient, simulate_read
from tests.os.test_choice_request_delivery import Flow
from tests.os.test_connect_t4_flow import run_rules, write
from tests.os.test_connect_t5_flow import (  # noqa: F401
    WINTER,
    chosen,
    germany_student,
    level,
    row_counts,
    run_os,
    svc,
    vault,
)
from tests.os.test_vault_check import by_field
from tests.test_roadmap_api import data, pre_eng
from tests.test_roadmap_choice_api import choose_with
from tests.os.connect_check import assert_consistent

pytestmark = [pytest.mark.req("R-16"), pytest.mark.req("R-01")]

TENANT = "pai"
SAMPLES = Path(__file__).parent / "fixtures" / "documents" / "samples"
ANSWERS = Path(__file__).parent / "rehearsal" / "answers"
CHAT = ("events", "pai_counselor_turn_decisions", "pai_turn_plans")  # the tables a chat message or turn would grow
UNTYPED_PDF = b"%PDF-1.4\n%untyped chat attachment\n"


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def chat_rows(who) -> dict[str, int]:
    """Rows a chat message or turn would make (the Vault logs `vault.*` events and an upload or a delete logs a
    `workspace.file.*` event: neither is chat)."""
    from app.models import Base

    events = Base.metadata.tables["events"]
    counts = row_counts(who)
    with who.factory() as db:
        counts["events"] = db.scalar(select(func.count()).select_from(events).where(
            ~events.c.type.like("vault.%"), ~events.c.type.like("workspace.file.%")))
    return {t: counts[t] for t in CHAT}


def no_chat(who, before: dict[str, int]) -> None:
    """Throughout (R-45): no message, turn or turn-plan row."""
    assert chat_rows(who) == {t: before[t] for t in CHAT}


# --- the world ---------------------------------------------------------------------------------------------------


class Clients:
    """The DBOS client the OS uses: a recording fake until a test starts the reader."""

    def __init__(self):
        self.client = FakeClient()


@pytest.fixture
def world(svc, engine, os_db, tmp_path, monkeypatch):  # noqa: F811
    """PAI OS on its ports with the Counsellor module on, every part of the flow on, the mailer stubbed."""
    from app.security import rate_limit
    from app.services import auth_emails

    clients = Clients()
    os_svc = replace(svc, dbos_client=lambda: clients.client, terms_dir=TEST_TERMS)
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id=TENANT, enabled=True))
    ports.configure(os_svc, choice_enabled=bridge.choice_enabled, student_facts=bridge.student_facts,
                    document_files=bridge.document_file_bytes, documents_enabled=bridge.documents_enabled,
                    on_document_deleted=bridge.on_os_document_deleted)  # no post-commit hook: the sweep delivers
    rate_limit.reset()
    monkeypatch.setattr(auth_emails, "send_email", lambda to, subject, html, text_body=None: True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    for part in ("CONNECT_ONE_UPLOAD", "CONNECT_STUDENT_FACTS", "CONNECT_HANDOFF", "CONNECT_ROADMAP_FROM_PLANVIEW"):
        monkeypatch.setattr(config, part, True, raising=False)
    monkeypatch.setattr("app.routers.roadmap.resolve_human", lambda db, ws, auth: SimpleNamespace())
    previous = storage._store
    storage._store = storage.LocalFileStore(str(tmp_path / "files"))
    try:
        yield SimpleNamespace(svc=os_svc, clients=clients, engine=engine, os_db=os_db)
    finally:
        storage._store = previous
        ports.configure(None)
        rate_limit.reset()


class Student:
    """One signed-in student on the Counsellor app, and the same student on the OS HTTP API."""

    def __init__(self, world, client, who, params, auth, os_client, other=None):
        self.world, self.svc, self.client, self.who, self.params = world, world.svc, client, who, params
        self.auth, self.os, self.other = auth, os_client, other
        self.id = who.workspace_id
        self.me = {"X-Test-Student": self.id}

    # -- consent, upload, OS reads
    def agree(self, ref: str | None = None):
        from app.os.consent import ConsentStore, current_terms

        ConsentStore(self.svc.engine, TENANT).agree(ref or self.id, current_terms(self.svc.terms_dir).version)

    def upload(self, name, data, doc_type="transcript", content_type="image/png", **fields):
        got = post_file(self.client, self.who, self.auth, name=name, data=data, content_type=content_type,
                        **({"doc_type": doc_type} if doc_type else {}), **fields)
        assert got.status_code == 200, got.text
        return got.json()["data"]

    def os_docs(self):
        with self.svc.engine.connect() as conn:
            return conn.execute(select(models.documents).where(models.documents.c.student_ref == self.id)
                                .order_by(models.documents.c.id)).all()

    def count(self, table) -> int:
        with self.svc.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar()

    def files(self):
        with self.who.factory() as db:
            return db.scalars(select(FileRecord).where(FileRecord.workspace_id == self.id)
                              .order_by(FileRecord.created_at)).all()

    def fields_of(self, doc_id) -> dict:
        """What the reader read (or the student confirmed), by field name, as the Documents page would send it back."""
        return {f["field"]: (f["value_confirmed"] if f["confirmed_at"] else f["value_read"])
                for f in DocumentStore(self.svc.engine, TENANT).fields(doc_id)}

    def status_of(self, doc_id) -> str:
        return DocumentStore(self.svc.engine, TENANT).get(doc_id).status

    def confirm(self, doc_id, values: dict | None = None, headers=None):
        values = values if values is not None else self.fields_of(doc_id)
        return self.os.post(f"/v1/os/documents/{doc_id}/confirm", json={"fields": values}, headers=headers or self.me)

    def vault_check(self, doc_id, headers=None):
        return self.os.get(f"/v1/os/documents/{doc_id}/vault-check", headers=headers or self.me)

    # -- the host sweeps, as the worker runs them
    def deliver(self) -> dict:
        """Hands the pending fact proposals to the Vault's sink, and runs the reconcile job inline on each candidate."""
        with self.who.factory() as db:
            got = bridge.deliver_fact_proposals(db)
            for candidate in db.scalars(select(MemoryCandidate).where(MemoryCandidate.status == "pending")
                                        .order_by(MemoryCandidate.id)).all():
                MemoryReconciler(db).reconcile(candidate)
            db.commit()
            bridge.deliver_pending(db, self.id)  # the Vault events the accepted candidates raised
        return got

    def proposals(self) -> list:
        with self.svc.engine.connect() as conn:
            return conn.execute(select(models.outbox).where(models.outbox.c.template == fact_proposals.TEMPLATE)
                                .order_by(models.outbox.c.id)).all()

    def vault_records(self, kind="education") -> list[dict]:
        from app.pai_c.memory import MemoryService

        with self.who.factory() as db:
            return list(MemoryService(db).profile(self.id).records[kind])

    def record_with(self, field: str) -> dict:
        """The education record whose result holds `field` (the student also has an FSc record from onboarding)."""
        (found,) = [r for r in self.vault_records() if field in (r.get("result") or {})]
        return found

    def reader_waits_for(self, doc_id, status="read", seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.status_of(doc_id) == status:
                return
            time.sleep(0.2)
        raise AssertionError(f"document {doc_id} is {self.status_of(doc_id)}, not {status}")


def os_api(svc_):
    app = FastAPI()
    app.include_router(build_router(lambda: svc_), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return TestClient(app)


@contextmanager
def signed_in(world, entry, with_b=False):
    """`entry` is a roadmap student context (`germany_student()` / `pre_eng()`); the student gets a Firebase bearer, so the
    upload routes work on the same session as the roadmap routes. `with_b` adds a second student on the same database."""
    with entry as (client, who, params):
        with who.factory() as db:
            token, identity = link_owner(db, db.get(User, who.user_id))
            tokens = {token: identity}
            other = None
            if with_b:
                user = User(email="student-b@example.test", username="student_b")
                db.add(user)
                db.flush()
                ws = Workspace(name="Student B", owner_user_id=user.id, password_hash="synthetic-test-only")
                db.add(ws)
                db.flush()
                user.firebase_uid = "uid-b"
                db.commit()
                tokens["token-uid-b"] = identity_for(user.email, "uid-b")
                other = SimpleNamespace(id=str(ws.id), auth={"Authorization": "Bearer token-uid-b"})
        with patch("app.database.new_session", lambda: who.factory()), \
                patch("app.database.SessionLocal", who.factory), \
                patch("app.routers.events.SessionLocal", who.factory), firebase_tokens(tokens):
            yield Student(world, client, who, params, {"Authorization": "Bearer " + token}, os_api(world.svc), other)


@contextmanager
def reader(world, student):
    """The OS document worker, in this process: DBOS on the test schema, the offline reader answering from the committed
    sample documents, the file read through the host adapter. Swaps the OS's DBOS client for the real one."""
    from dbos import DBOS, DBOSClient

    from app.os.agents.offline import offline_model
    from app.os.agents.spec import AGENT_DIR, load_agent_spec
    from app.os.documents.checks import load_name_variants
    from app.os.documents.reader import build_readers
    from app.os.documents.run import register_documents
    from app.os.documents.types import load_document_types
    from app.os.kernel import Kernel
    from app.os.runner import (
        APP_NAME,
        dbos_config,
        default_registry,
        launch,
        register_workflow,
    )
    from app.os.settings import load_settings
    from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema

    engine = world.engine
    os_db = world.os_db
    types, spec = load_document_types(), load_agent_spec(AGENT_DIR / "documents.v1.yaml")
    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
                              "OS_MODEL_MODE": "offline", "OS_REHEARSAL": "on", "OS_OFFLINE_ANSWERS_DIR": str(ANSWERS)})
    readers = build_readers(offline_model("documents", ANSWERS), types, spec)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, TENANT))
    register_documents(engine, settings, readers, spec, types, load_name_variants())
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    world.clients.client = client
    try:
        yield client
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


# --- 1. Germany: the whole route (row 6.7) -------------------------------------------------------------------------

TRANSCRIPT_FILE = "b2_transcript.png"  # the sample key: CGPA 3.2 on a scale of 4.0


@pytest.mark.connect_row("6.7")
def test_germany_transcript_from_upload_to_replan(world):
    with signed_in(world, germany_student()) as s, level("master"):
        vault((s.client, s.who, s.params))
        before = chat_rows(s.who)
        # 1. choose with places: planned
        data(choose_with(s.client, s.params, destination="DE", places=[{"ref": "ovgu-eeit", "rank": 1}],
                         intake=WINTER))
        assert run_os(world.svc) == [("planned", None)]
        plan_id = Flow(world.svc, s.client, s.who, s.params).plan_id()
        s.agree()

        # 2. the Documents page uploads a typed transcript through the one endpoint; 3. the worker reads it through
        # the adapter (the reader is started first, so the upload's workflow reaches it)
        with reader(world, s):
            got = s.upload(TRANSCRIPT_FILE, sample(TRANSCRIPT_FILE))
            (record,) = s.files()
            (row,) = s.os_docs()
            assert record.id == got["id"] and row.file_ref == record.id and got["os_document"]["id"] == row.id
            assert s.count(models.document_files) == 0  # the OS keeps no bytes of its own
            doc_id = row.id
            s.reader_waits_for(doc_id, "read")
        values = s.fields_of(doc_id)
        assert values["cgpa"] == 3.2 and values["cgpa_scale"] == 4.0

        # 4. the Vault holds no CGPA yet: the check says new
        check = by_field(s.vault_check(doc_id).json())
        assert (check["cgpa"], check["cgpa_scale"]) == ("new", "new")
        assert s.vault_check(doc_id).json()["note"] is None

        # 5. confirm: a fact proposal, delivered, reconciled
        assert s.confirm(doc_id).status_code == 200
        (proposal,) = s.proposals()
        assert proposal.status == "pending"
        assert s.deliver()["written"] == 1
        education = s.record_with("gpa")
        assert education["result"]["gpa"] == 3.2 and education["evidence_level"] == "shown"
        assert education["evidence"]["file_id"] == record.id

        # 6. the Vault version was raised and the event went to the OS, which re-evaluates the plan
        with world.svc.engine.connect() as conn:
            fact_events = conn.execute(select(models.events.c.payload).where(
                models.events.c.type == "student_fact_changed", models.events.c.plan_id == plan_id)).all()
        assert fact_events
        flow = Flow(world.svc, s.client, s.who, s.params)
        decisions = run_rules(SimpleNamespace(engine=world.svc.engine, replanner=flow.r), plan_id)
        assert decisions and all(d.status in ("applied", "pending") for d in decisions)

        # 7. profile_of reads the GPA from StudentFacts only
        assert profile_of(world.svc.plans, s.id)["transcript.cgpa"] == 3.2
        with patch.object(ProfileStore, "all", return_value=[{"key": "transcript.cgpa", "value": 9.9}]):
            assert profile_of(world.svc.plans, s.id)["transcript.cgpa"] == 3.2  # os_profile_values is not read for it

        # 8. the plan needs the transcript, and it is confirmed
        needs = {n["doc_type"]: n["status"] for n in bridge.plan_view(s.id)["documents_needed"]}
        assert needs["transcript"] == "confirmed"
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


# --- 2. R-16: the student said 3.4, the transcript shows 3.2 -----------------------------------------------------------


def read_transcript(s, world):
    """Uploads the sample transcript (CGPA 3.2 on 4.0) typed, and waits for the offline reader."""
    with reader(world, s):
        doc_id = s.upload(TRANSCRIPT_FILE, sample(TRANSCRIPT_FILE))["os_document"]["id"]
        s.reader_waits_for(doc_id, "read")
    return doc_id


def test_a_stated_value_and_a_transcript_value_are_compared_and_never_overwritten_silently(world):
    from app.memory.profile_issues import ProfileIssueService

    with signed_in(world, germany_student()) as s:
        s.agree()
        before = chat_rows(s.who)
        with s.who.factory() as db:  # the student told PAI 3.4 (stated)
            write(db, s.id, "student_record", "education", {"qualification_name": "bachelor",
                  "academic_status": "completed", "result": {"gpa": 3.4, "gpa_scale": 4.0}})
        assert s.record_with("gpa")["evidence_level"] == "stated"
        doc_id = read_transcript(s, world)

        # before the confirm: the check says the Vault differs (and where it agrees), with the plain sentence
        check = s.vault_check(doc_id).json()
        assert by_field(check)["cgpa"] == "differs" and by_field(check)["cgpa_scale"] == "same"
        assert check["note"]

        # after the confirm: the Vault's reconciler decides. A stated value is not overwritten by a document: one
        # conflict card holds both values and both sources (the Vault rule for education, T8 shows it as "which is right")
        assert s.confirm(doc_id).status_code == 200
        assert s.deliver()["written"] == 1
        record = s.record_with("gpa")
        assert record["result"]["gpa"] == 3.4 and record["evidence_level"] == "stated"
        with s.who.factory() as db:
            (issue,) = db.scalars(select(ProfileIssue)).all()
            assert issue.status == "open" and issue.evidence["current"]["result"]["gpa"] == 3.4
            assert issue.evidence["proposed"]["result"]["gpa"] == 3.2
            assert issue.evidence["proposed_evidence"]["file_id"] == s.files()[0].id
            assert issue.evidence["proposed_evidence"]["os_confirmed"] is True
            (needs_review,) = db.scalars(select(MemoryCandidate).where(MemoryCandidate.status == "needs_review")).all()
            assert needs_review.proposed_value["value"]["result"]["gpa"] == 3.2
        # the student reads the card and takes the transcript's value: the Vault now holds 3.2 (the student's decision)
        with s.who.factory() as db:
            assert ProfileIssueService(db).resolve(s.id, issue.id, "accept_proposed", capture="vault_api")["resolved"]
            db.commit()
        assert s.record_with("gpa")["result"]["gpa"] == 3.2
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


def test_a_transcript_value_then_a_different_chat_value_keeps_the_document_visible(world):
    """The other order (Vault spec, evidence ladder): the document is `shown` first; the student's own later word wins
    and the disagreeing document stays on the entry (`merge_disagreements`)."""
    with signed_in(world, germany_student()) as s:
        s.agree()
        before = chat_rows(s.who)
        doc_id = read_transcript(s, world)
        assert s.confirm(doc_id).status_code == 200
        s.deliver()
        record = s.record_with("gpa")
        assert record["result"]["gpa"] == 3.2 and record["evidence_level"] == "shown"
        # the check now agrees
        assert by_field(s.vault_check(doc_id).json())["cgpa"] == "same"
        with s.who.factory() as db:  # the student says 3.4 in chat
            write(db, s.id, "student_record", "education", {"result": {"gpa": 3.4}},
                  entities={"record_id": record["id"]})
        record = s.record_with("gpa")
        assert record["result"]["gpa"] == 3.4 and record["evidence_level"] == "stated"
        (kept,) = record["evidence"]["disagreements"]  # the document stays visible on the entry
        assert kept["value"]["result"]["gpa"] == 3.2 and kept["file_id"] == s.files()[0].id
        check = s.vault_check(doc_id).json()
        assert by_field(check)["cgpa"] == "differs" and check["note"]
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


# --- 3. the fake Pakistan intermediate route: per part (R-80) -----------------------------------------------------------

HSSC_FILE = "b1_hssc_certificate.png"  # the sample key: marks 910 of 1100
PARTS = {"part1": {"marks_obtained": 400, "marks_total": 550}}


def test_intermediate_certificate_keeps_the_onboarding_part_and_asks_nothing_in_chat(world):
    with signed_in(world, pre_eng()) as s, level("intermediate"):
        vault((s.client, s.who, s.params))
        s.agree()
        before = chat_rows(s.who)
        data(choose_with(s.client, s.params, destination="PK", places=[{"ref": "pk-i1", "rank": 1}], intake=WINTER))
        assert run_os(world.svc) == [("planned", None)]
        (fsc,) = s.vault_records()
        with s.who.factory() as db:  # onboarding already holds part one of the two-part result
            write(db, s.id, "student_record", "education", {"result": PARTS}, entities={"record_id": fsc["id"]})
        assert s.record_with("part1")["result"]["part1"] == PARTS["part1"]

        with reader(world, s):
            doc_id = s.upload(HSSC_FILE, sample(HSSC_FILE), doc_type="hssc_certificate")["os_document"]["id"]
            s.reader_waits_for(doc_id, "read")
        values = s.fields_of(doc_id)
        assert (values["marks_obtained"], values["marks_total"]) == (910, 1100)
        by = by_field(s.vault_check(doc_id).json())
        assert by["marks_obtained"] == "new" and by["marks_total"] == "new"  # the Vault holds part one, not the totals
        assert s.confirm(doc_id).status_code == 200
        (proposal,) = s.proposals()
        keys = {f["key"] for f in proposal.payload["facts"]}
        assert keys == {"education.intermediate.marks_obtained", "education.intermediate.marks_total"}  # no part keys
        assert s.deliver()["written"] == 1
        (record,) = s.vault_records()
        assert record["id"] == fsc["id"]  # the same record: no second intermediate entry
        assert record["result"]["part1"] == PARTS["part1"]  # R-80: the part from onboarding is kept
        assert (record["result"]["marks_obtained"], record["result"]["marks_total"]) == (910, 1100)
        assert record["result"]["percentage"] == 78
        with s.who.factory() as db:
            assert db.scalars(select(ProfileIssue)).all() == []  # nothing is asked
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


# --- 4. a chat attachment ----------------------------------------------------------------------------------------------


def test_a_chat_attachment_keeps_todays_extraction_and_can_become_an_os_document_later(world):
    with signed_in(world, germany_student()) as s:
        s.agree()
        before = chat_rows(s.who)
        # 1. an untyped PDF: today's Counsellor pipeline (parse, then extraction; the model is not called here)
        file_id = s.upload("attachment.pdf", PDF, doc_type=None, content_type="application/pdf")["id"]
        assert s.os_docs() == []  # no OS document
        run_parse_job(s.who, file_id)
        assert [p["file_id"] for _, p in jobs(s.who, "document.extract")] == [file_id]  # extraction is queued, once
        # 2. the student then says what it is: an OS document, linked to the same file
        got = s.client.post(f"/v1/uploads/{file_id}/os-document", params={"network": s.id}, headers=s.auth,
                            json={"doc_type": "transcript"})
        assert got.status_code == 200, got.text
        (row,) = s.os_docs()
        assert row.file_ref == file_id and got.json()["data"]["os_document"]["id"] == row.id
        assert s.count(models.document_files) == 0 and len(s.files()) == 1  # still one stored copy
        # 3. from then on there is no second extraction of that file, and no second parse
        assert [p["file_id"] for _, p in jobs(s.who, "document.extract")] == [file_id]
        assert len([1 for _, p in jobs(s.who, "document.parse") if p.get("file_id") == file_id]) == 1
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


def test_a_typed_file_reaches_done_in_the_chat_context_with_todays_wording(world):
    from app.documents.progress import (
        STAGE_DONE,
        document_stage,
        recent_documents_block,
    )
    from app.documents.service import DocumentArtifactService

    with signed_in(world, germany_student()) as s:
        s.agree()
        file_id = s.upload("t.pdf", PDF, content_type="application/pdf")["id"]
        doc_id = s.os_docs()[0].id
        run_parse_job(s.who, file_id)
        with s.who.factory() as db:
            assert document_stage(DocumentArtifactService(db).get(s.id, file_id)) == STAGE_DONE
            line = next(l for l in recent_documents_block(db, s.id).splitlines() if file_id in l)
        assert "in progress" not in line and "finished" in line
        simulate_read(world.svc.engine, doc_id, "transcript", TRANSCRIPT)
        assert s.confirm(doc_id).status_code == 200 and s.deliver()["written"] == 1
        with s.who.factory() as db:
            line = next(l for l in recent_documents_block(db, s.id).splitlines() if file_id in l)
        assert "in progress" not in line and "finished" in line and "education" in line  # the line counts the fact
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


# --- 5. deletion deletes in both places; the Vault facts stay ------------------------------------------------------------


def test_deleting_from_either_side_removes_both_and_the_vault_facts_stay(world):
    from app.files.storage import get_file_store

    with signed_in(world, germany_student()) as s:
        s.agree()
        before = chat_rows(s.who)
        first = s.upload("one.pdf", PDF, content_type="application/pdf")
        second = s.upload("two.pdf", PDF + b"\n%two", content_type="application/pdf")
        one, two = first["os_document"]["id"], second["os_document"]["id"]
        simulate_read(world.svc.engine, one, "transcript", TRANSCRIPT)
        assert s.confirm(one).status_code == 200 and s.deliver()["written"] == 1
        learned = s.record_with("gpa")
        assert learned["result"]["gpa"] == 3.7 and learned["evidence_level"] == "shown"
        keys = {r.id: r.storage_key for r in s.files()}

        # an OS delete purges the Counsellor file (record and bytes)
        assert s.os.delete(f"/v1/os/documents/{one}", headers=s.me).status_code == 204
        assert first["id"] not in {r.id for r in s.files()} and not get_file_store().exists(keys[first["id"]])
        assert DocumentStore(world.svc.engine, TENANT).get(one).status == "deleted"
        # a Counsellor trash of the other typed file deletes its OS document
        trashed = s.client.post("/v1/files/trash", headers=s.auth, json={"network": s.id, "file_ids": [second["id"]]})
        assert trashed.status_code == 200 and trashed.json()["data"]["trashed_count"] == 1
        assert DocumentStore(world.svc.engine, TENANT).get(two).status == "deleted"
        assert [r.status for r in s.files()] == ["deleted"]

        # what the Vault learned stays: a purge is not a retraction
        after = s.record_with("gpa")
        assert after["result"]["gpa"] == 3.7 and after["evidence_level"] == "shown"
        assert after["evidence"]["file_id"] == first["id"]
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


# --- 6. isolation: every read checks the tenant and the student ------------------------------------------------------


def test_student_b_cannot_read_confirm_check_or_register_student_as_file(world):
    with signed_in(world, germany_student(), with_b=True) as s:
        b = s.other
        s.agree()
        s.agree(b.id)
        a_file = s.upload("a.pdf", PDF, content_type="application/pdf")
        a_doc = a_file["os_document"]["id"]
        simulate_read(world.svc.engine, a_doc, "transcript", TRANSCRIPT)
        assert s.confirm(a_doc).status_code == 200
        hb = {"X-Test-Student": b.id}
        # the OS routes: A's document is not found for B, whatever the verb
        assert s.os.get("/v1/os/documents", headers=hb).json()["documents"] == []
        assert s.vault_check(a_doc, headers=hb).status_code == 404
        assert s.confirm(a_doc, headers=hb).status_code == 404
        assert s.os.delete(f"/v1/os/documents/{a_doc}", headers=hb).status_code == 404
        assert DocumentStore(world.svc.engine, TENANT).get(a_doc).status == "confirmed"
        # the Counsellor route: B cannot make A's stored file an OS document, on B's network or on A's
        mine = {"doc_type": "transcript"}
        assert s.client.post(f"/v1/uploads/{a_file['id']}/os-document", params={"network": b.id}, headers=b.auth,
                             json=mine).status_code == 404
        assert s.client.post(f"/v1/uploads/{a_file['id']}/os-document", params={"network": s.id}, headers=b.auth,
                             json=mine).status_code in (401, 403)
        assert len(s.os_docs()) == 1 and world_docs_of(world, b.id) == []
        # the adapter: B's read of A's file, and another tenant's read of A's document
        with pytest.raises(KeyError):
            bridge.document_file_bytes(b.id, a_file["id"])
        with pytest.raises(KeyError):
            DocumentStore(world.svc.engine, "other-tenant").file_bytes(a_doc)
        # the OS port refuses to link A's live file to B, and a B row that names A's file is never read
        with pytest.raises(document_files.Refused) as refused:
            document_files.register(b.id, "transcript", a_file["id"], "x.pdf", PDF + b"\n%b")
        assert refused.value.code == "duplicate"
        assert s.os.delete(f"/v1/os/documents/{a_doc}", headers=s.me).status_code == 204  # A's link is gone...
        again = s.upload("a.pdf", PDF + b"\n%again", doc_type=None, content_type="application/pdf")
        store = DocumentStore(world.svc.engine, TENANT)
        stray = store.create_ref(b.id, "transcript", 1, "x.pdf", "application/pdf", PDF, again["id"])  # ...B names A's file
        with pytest.raises(KeyError):
            store.file_bytes(stray)
            assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)


def world_docs_of(world, ref):
    with world.svc.engine.connect() as conn:
        return conn.execute(select(models.documents).where(models.documents.c.student_ref == ref)).all()


# --- 7. module off (standalone) -----------------------------------------------------------------------------------------


def test_module_off_stores_bytes_in_the_os_reads_them_and_makes_no_outbox_row(world):
    with signed_in(world, germany_student()) as s, reader(world, s):
        s.agree()
        # a typed upload while the part is on: the OS keeps no bytes
        linked = s.upload(TRANSCRIPT_FILE, sample(TRANSCRIPT_FILE))["os_document"]["id"]
        s.reader_waits_for(linked, "read")
        # the Counsellor module goes off
        with world.svc.engine.begin() as conn:
            conn.execute(update(models.modules).where(models.modules.c.module == "counsellor").values(enabled=False))
        assert bridge.documents_enabled() is False
        # 1. the OS route stores bytes in os_document_files, as it always did
        other = "b3_transcript.png"
        got = s.os.post("/v1/os/documents", data={"doc_type": "transcript"},
                        files={"file": (other, sample(other), "image/png")}, headers=s.me)
        assert got.status_code == 201, got.text
        standalone = got.json()["id"]
        assert s.count(models.document_files) == 1
        with world.svc.engine.connect() as conn:
            assert conn.execute(select(models.documents.c.file_ref).where(
                models.documents.c.id == standalone)).scalar() is None
        # 2. the reader reads them
        s.reader_waits_for(standalone, "read")
        assert s.fields_of(standalone)["cgpa"] is not None
        # 3. confirming makes no outbox row, for a document of its own bytes or a linked one
        assert s.confirm(standalone).status_code == 200 and s.confirm(linked).status_code == 200
        assert s.proposals() == []
        # 4. a ref-backed document still reads through the adapter (D-y6)
        store = DocumentStore(world.svc.engine, TENANT)
        assert store.file_bytes(linked) == sample(TRANSCRIPT_FILE)
        assert store.file_bytes(standalone) == sample(other)


# --- 8. corrections ------------------------------------------------------------------------------------------------------


def test_a_reconfirmation_replaces_the_value_and_another_source_still_conflicts(world):
    with signed_in(world, germany_student()) as s:
        s.agree()
        before = chat_rows(s.who)
        file = s.upload("t.pdf", PDF, content_type="application/pdf")
        doc_id = file["os_document"]["id"]
        simulate_read(world.svc.engine, doc_id, "transcript", TRANSCRIPT)
        values = s.fields_of(doc_id)
        assert s.confirm(doc_id, values).status_code == 200 and s.deliver()["written"] == 1
        assert s.record_with("gpa")["result"]["gpa"] == 3.7
        # 1. the student corrects the same document: the value is replaced, no card
        assert s.confirm(doc_id, {**values, "cgpa": 3.5}).status_code == 200 and s.deliver()["written"] == 1
        record = s.record_with("gpa")
        assert record["result"]["gpa"] == 3.5 and record["evidence_level"] == "stated"  # the student's own correction
        assert record["evidence"]["file_id"] == file["id"] and record["evidence"]["os_confirmed"] is True
        (earlier,) = record["evidence"]["disagreements"]  # the first reading stays visible
        assert earlier["value"]["result"]["gpa"] == 3.7
        with s.who.factory() as db:
            assert db.scalars(select(ProfileIssue)).all() == []
        # 2. the student then says another number in chat: the record belongs to that statement
        with s.who.factory() as db:
            write(db, s.id, "student_record", "education", {"result": {"gpa": 3.0}}, entities={"record_id": record["id"]})
        assert s.record_with("gpa")["result"]["gpa"] == 3.0
        # 3. a further correction of the document is now a conflict, not a silent overwrite
        assert s.confirm(doc_id, {**values, "cgpa": 3.3}).status_code == 200 and s.deliver()["written"] == 1
        assert s.record_with("gpa")["result"]["gpa"] == 3.0
        with s.who.factory() as db:
            (issue,) = db.scalars(select(ProfileIssue)).all()
            assert issue.status == "open"
            assert [c.status for c in db.scalars(select(MemoryCandidate).where(
                MemoryCandidate.status == "needs_review")).all()] == ["needs_review"]
        no_chat(s.who, before)
        assert_consistent(s.who.factory)  # the end-of-test check (R-04, R-05)
