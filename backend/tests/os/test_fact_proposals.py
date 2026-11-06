"""P1-T7 Task 3 (R-16, R-01, row 6.7): a document the student confirms offers its `fact:` fields to the Vault. The OS
side is the real services on Postgres; the Counsellor side is the real bridge on a student session (SQLite, a temp file
store). The reader is not run (no model): a read document is stored the way the workflow stores it. Fictional data."""

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from app import pai_os_bridge as bridge
from app.config import config
from app.models import DocumentProposal, FileRecord, MemoryCandidate
from app.os import models, ports
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.fact_proposal import FactProposalV1
from app.os.documents.store import DocumentStore
from app.os.playbooks import load_playbook_dir
from app.os.ports import fact_proposals
from app.os.settings import load_settings
from tests.one_upload_support import PDF, post_file, upload_world
from tests.os.test_api import TEST_TERMS, TOKEN
from tests.os.test_api_documents import TYPES, FakeClient, confirm_body, simulate_read

pytestmark = pytest.mark.req("R-16")

FAKE = __import__("pathlib").Path(__file__).parent / "playbooks"
TENANT = "pai"
O = models.outbox
HSSC = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Raza Khan", "date_of_birth": "2001-04-12",
        "board": "Board of Example", "exam_year": 2022, "roll_number": "123456", "group": "SCIENCE",
        "institution": "A College", "marks_obtained": 900, "marks_total": 1100, "grade": "A1",
        "issue_date": "2022-09-01"}


class World:
    def __init__(self, client, who, auth, svc, os_client):
        self.client, self.who, self.auth, self.svc, self.os = client, who, auth, svc, os_client
        self.id = who.workspace_id
        self.me = {"X-Test-Student": self.id}

    def agree(self):
        from app.os.consent import ConsentStore, current_terms

        ConsentStore(self.svc.engine, TENANT).agree(self.id, current_terms(self.svc.terms_dir).version)

    def typed(self, doc_type="hssc_certificate", data=PDF, name="hssc.pdf") -> int:
        """A document registered by a typed upload (bytes in the Counsellor store, `file_ref` on the OS row)."""
        self.agree()
        got = post_file(self.client, self.who, self.auth, name=name, data=data, doc_type=doc_type)
        assert got.status_code == 200, got.text
        return got.json()["data"]["os_document"]["id"]

    def os_only(self, doc_type="hssc_certificate", data=PDF + b"%os-only") -> int:
        """A document the OS stored itself (uploaded before the part was on)."""
        return DocumentStore(self.svc.engine, TENANT).create(
            self.id, doc_type, TYPES[doc_type].version, "old.pdf", "application/pdf", data)

    def read(self, doc_id, doc_type="hssc_certificate", values=HSSC):
        simulate_read(self.svc.engine, doc_id, doc_type, values)

    def confirm(self, doc_id, doc_type="hssc_certificate", values=HSSC):
        got = self.os.post(f"/v1/os/documents/{doc_id}/confirm", json=confirm_body(doc_type, values), headers=self.me)
        assert got.status_code == 200, got.text
        return got

    def rows(self) -> list:
        with self.svc.engine.connect() as conn:
            return conn.execute(select(O).where(O.c.template == fact_proposals.TEMPLATE).order_by(O.c.id)).all()

    def candidates(self) -> list:
        with self.who.factory() as db:
            return db.scalars(select(MemoryCandidate).where(MemoryCandidate.key.in_(("education", "test_attempt")))
                              ).all()

    def intake(self, status="planned"):
        with self.svc.engine.begin() as conn:
            conn.execute(insert(models.counsellor_intake).values(
                tenant_id=TENANT, decision_id="d1", student_ref=self.id, journey_id="j1", export={},
                export_sha256="x", chosen_at=fact_proposals._EPOCH, status=status))


@pytest.fixture
def world(engine, clean, os_db, tmp_path, monkeypatch):
    fake = FakeClient()
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: fake,
                        terms_dir=TEST_TERMS)
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id=TENANT, enabled=True))
    ports.configure(svc, document_files=bridge.document_file_bytes, documents_enabled=bridge.documents_enabled,
                    on_document_deleted=bridge.on_os_document_deleted)  # no post-commit hook: the sweep delivers
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
            yield World(client, who, auth, svc, TestClient(app))
    finally:
        ports.configure(None)


# --- the contract and the fields -------------------------------------------------------------------------------


def test_contract_rejects_names_and_extra_fields():
    base = {"key": "fact_proposal:1:1", "student_ref": "s", "document_ref": "f", "doc_type": "hssc_certificate",
            "confirmed_at": "2026-11-05T09:00:00+00:00", "facts": [{"key": "education.intermediate.gpa", "value": 3}]}
    FactProposalV1.model_validate(base)
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate({**base, "full_name": "Sara"})
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate({**base, "facts": [{"key": "identity.full_name", "value": "Sara", "x": 1}]})
    # a name is not refused by the schema itself, so the fields are what keeps it out: only `fact:` fields are listed
    doc = type("D", (), {"doc_type": "hssc_certificate"})()
    facts = fact_proposals.facts_of(doc, TYPES, HSSC)
    assert {f["key"] for f in facts} == {"education.intermediate.marks_obtained",
                                         "education.intermediate.marks_total"}
    assert "Sara" not in repr(facts) and "2001" not in repr(facts)
    assert fact_proposals.facts_of(doc, TYPES, {**HSSC, "marks_obtained": "  ", "marks_total": None}) == []
    assert fact_proposals.facts_of(type("D", (), {"doc_type": "passport"})(), TYPES, HSSC) == []


# --- confirm writes one outbox row -----------------------------------------------------------------------------


def test_confirm_emits_one_proposal_with_only_fact_fields(world):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    (row,) = world.rows()
    assert (row.channel, row.template, row.status, row.recipient) == ("counsellor", "fact_proposal", "pending",
                                                                      world.id)
    proposal = FactProposalV1.model_validate(row.payload)
    assert [f.key for f in proposal.facts] == ["education.intermediate.marks_obtained",
                                               "education.intermediate.marks_total"]
    assert [f.value for f in proposal.facts] == [900, 1100]
    (file_record,) = [r for r in world.who.factory().__enter__().scalars(select(FileRecord)).all()]
    assert proposal.document_ref == file_record.id and proposal.student_ref == world.id
    assert "Sara" not in str(row.payload) and "2001-04-12" not in str(row.payload)


def test_reconfirm_emits_a_new_key_and_retry_does_not(world):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    (first,) = world.rows()
    doc = DocumentStore(world.svc.engine, TENANT).get(doc_id)
    facts = fact_proposals.facts_of(doc, TYPES, HSSC)
    with world.svc.engine.begin() as conn:
        assert fact_proposals.emit(conn, TENANT, doc, facts) is None  # a retry of the same confirmation
    assert len(world.rows()) == 1
    world.confirm(doc_id, values={**HSSC, "marks_obtained": 910})
    keys = [r.idempotency_key for r in world.rows()]
    assert len(keys) == 2 and keys[0] == first.idempotency_key and keys[1] != keys[0]


def test_confirm_with_port_off_writes_no_outbox_row(world):
    """The module is on but the host never configured `enabled`, and the document has no file link: today's confirm."""
    doc_id = world.os_only()
    world.read(doc_id)
    ports.configure(world.svc)  # nothing configured
    world.confirm(doc_id)
    assert world.rows() == []


def test_confirm_failure_to_emit_never_fails_the_confirmation(world, monkeypatch):
    doc_id = world.typed()
    world.read(doc_id)

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(fact_proposals, "emit", boom)
    got = world.confirm(doc_id)
    assert got.json()["status"] == "confirmed" and world.rows() == []


def test_typed_document_with_the_part_off_writes_no_row(world):
    """Confirm runs in the API, where `enabled()` is configured: with it off a linked document proposes nothing."""
    doc_id = world.typed()
    world.read(doc_id)
    ports.configure(world.svc, document_files=bridge.document_file_bytes)  # `enabled` unconfigured
    world.confirm(doc_id)
    assert world.rows() == []


# --- delivery --------------------------------------------------------------------------------------------------


def delivered(world):
    with world.who.factory() as db:
        return bridge.deliver_fact_proposals(db)


def test_delivery_writes_candidates_once_and_marks_the_row(world):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    assert delivered(world) == {"written": 1, "duplicate": 0, "refused": 0, "failed": 0}
    (candidate,) = world.candidates()
    with world.who.factory() as db:
        record = db.scalar(select(FileRecord))
        assert candidate.evidence["file_id"] == record.id and candidate.evidence["os_confirmed"] is True
        assert candidate.source_type == "document" and candidate.entities is None
        assert len(db.scalars(select(DocumentProposal)).all()) == 1
    (row,) = world.rows()
    assert row.status == "sent" and row.payload["outcome"] == "written"
    assert delivered(world) == {"written": 0, "duplicate": 0, "refused": 0, "failed": 0}  # nothing pending now


def test_a_lost_mark_is_a_duplicate_not_a_second_set(world):
    """Crash between the Counsellor commit and the OS mark: the row is still pending; the repeat finds the key."""
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    delivered(world)
    with world.svc.engine.begin() as conn:
        conn.execute(update(O).where(O.c.template == "fact_proposal").values(status="pending"))
    assert delivered(world)["duplicate"] == 1
    assert len(world.candidates()) == 1
    (row,) = world.rows()
    assert row.status == "sent" and row.payload["outcome"] == "duplicate"


def test_a_file_that_is_not_the_students_is_refused_and_set_aside(world):
    doc_id = world.os_only()
    world.read(doc_id)
    world.confirm(doc_id)
    with world.svc.engine.begin() as conn:  # the row names a file that does not exist in this student's workspace
        conn.execute(update(O).where(O.c.template == "fact_proposal").values(
            payload=O.c.payload.concat({"document_ref": "someone-elses-file"})))
    assert delivered(world)["refused"] == 1
    (row,) = world.rows()
    assert row.status == "skipped" and row.payload["outcome"] == "refused:file_not_yours"
    assert world.candidates() == []


def test_os_only_document_is_stated(world):
    doc_id = world.os_only()
    world.read(doc_id)
    world.confirm(doc_id)
    (row,) = world.rows()
    assert row.payload["document_ref"] == f"os:{doc_id}"
    assert delivered(world)["written"] == 1
    (candidate,) = world.candidates()
    assert "file_id" not in candidate.evidence and "authority" not in candidate.evidence


def test_the_post_commit_hook_delivers_at_once(world):
    ports.configure(world.svc, document_files=bridge.document_file_bytes, documents_enabled=bridge.documents_enabled,
                    on_document_deleted=bridge.on_os_document_deleted, on_fact_proposal=bridge.deliver_fact_proposal_now)
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    (row,) = world.rows()
    assert row.status == "sent" and len(world.candidates()) == 1


def test_notify_errors_are_swallowed(world):
    def boom(key):
        raise RuntimeError("secret value")

    fact_proposals.configure(boom)
    fact_proposals.notify("fact_proposal:1:1")  # no raise
    fact_proposals.notify(None)


# --- backfill and the sweep ------------------------------------------------------------------------------------


def test_backfill_covers_a_crash_between_confirm_and_emit(world, monkeypatch):
    doc_id = world.typed()
    world.read(doc_id)
    with monkeypatch.context() as m:
        m.setattr(fact_proposals, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("killed")))
        world.confirm(doc_id)
    assert world.rows() == []
    assert fact_proposals.backfill() == 0  # no Counsellor decision for this student yet
    world.intake()
    assert fact_proposals.backfill() == 1 and fact_proposals.backfill() == 0
    assert delivered(world)["written"] == 1 and len(world.candidates()) == 1
    assert fact_proposals.backfill() == 0 and delivered(world)["written"] == 0


def test_sweep_delivers_fact_proposals_when_one_upload_is_on(world):
    doc_id = world.typed()
    world.read(doc_id)
    world.intake()
    with world.svc.engine.begin() as conn:  # confirmed long ago, never proposed (the part was off)
        conn.execute(update(models.documents).where(models.documents.c.id == doc_id).values(
            status="confirmed", confirmed_at=func.now()))
        for name, v in HSSC.items():
            conn.execute(update(models.document_fields).where(
                models.document_fields.c.document_id == doc_id, models.document_fields.c.field == name
            ).values(value_confirmed=v))
    with world.who.factory() as db:
        bridge.sweep_once(db)
    assert len(world.candidates()) == 1
    (row,) = world.rows()
    assert row.status == "sent"


def test_sweep_skips_fact_proposals_when_one_upload_off(world, monkeypatch):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    world.intake()
    monkeypatch.setattr(config, "CONNECT_ONE_UPLOAD", False)
    with world.who.factory() as db:
        bridge.sweep_once(db)
        assert bridge.deliver_fact_proposals(db) == {"written": 0, "duplicate": 0, "refused": 0, "failed": 0}
    (row,) = world.rows()
    assert row.status == "pending" and world.candidates() == []
    bridge.deliver_fact_proposal_now(row.idempotency_key)  # the nudge is off too
    assert world.candidates() == []


def test_a_confirmed_typed_document_ends_as_a_shown_fact_in_the_vault(world):
    from app.memory.reconciler import MemoryReconciler
    from app.pai_c.memory import MemoryService

    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    delivered(world)
    with world.who.factory() as db:
        for candidate in db.scalars(select(MemoryCandidate)).all():
            assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()
        (row,) = MemoryService(db).profile(world.id).records["education"]
        file_id = db.scalar(select(FileRecord.id))
    assert row["evidence_level"] == "shown" and row["evidence"]["file_id"] == file_id
    assert row["result"] == {"marks_obtained": 900, "marks_total": 1100}


# --- review round: current key, superseded, attempts -------------------------------------------------------------


def test_backfill_recovers_a_failed_emit_of_a_reconfirmation(world, monkeypatch):
    doc_id = world.typed()
    world.read(doc_id)
    world.intake()
    world.confirm(doc_id)
    assert delivered(world)["written"] == 1
    with monkeypatch.context() as m:
        m.setattr(fact_proposals, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("killed")))
        world.confirm(doc_id, values={**HSSC, "marks_obtained": 910})
    assert len(world.rows()) == 1  # the new confirmation has no row, an older one is on file
    assert fact_proposals.backfill() == 1 and fact_proposals.backfill() == 0
    assert delivered(world)["written"] == 1
    values = sorted(str(c.proposed_value["value"]["result"].get("marks_obtained")) for c in world.candidates())
    assert values == ["900", "910"]


def test_only_the_newest_proposal_of_a_document_is_delivered(world):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    world.confirm(doc_id, values={**HSSC, "marks_obtained": 905})
    world.confirm(doc_id, values={**HSSC, "marks_obtained": 910})
    assert len(world.rows()) == 3
    assert delivered(world) == {"written": 1, "duplicate": 0, "refused": 0, "failed": 0}
    first, second, third = world.rows()
    assert [r.status for r in (first, second, third)] == ["skipped", "skipped", "sent"]
    assert first.payload["outcome"] == second.payload["outcome"] == "superseded"
    (candidate,) = world.candidates()
    assert candidate.proposed_value["value"]["result"]["marks_obtained"] == 910


def test_reconfirming_the_same_values_makes_one_set_of_candidates(world):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    assert delivered(world)["written"] == 1
    world.confirm(doc_id)  # a new confirmation, the same values
    assert len(world.rows()) == 2
    assert delivered(world)["duplicate"] == 1
    assert len(world.candidates()) == 1


def test_a_row_that_keeps_failing_is_set_aside_after_five_tries(world, monkeypatch):
    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    from app.pai_c.connect import document_facts

    monkeypatch.setattr(document_facts, "apply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    for n in range(1, 5):
        assert delivered(world)["failed"] == 1
        (row,) = world.rows()
        assert row.status == "pending" and row.attempts == n
    assert delivered(world)["failed"] == 1
    (row,) = world.rows()
    assert row.status == "failed" and row.payload["outcome"] == "failed"
    assert delivered(world)["failed"] == 0 and fact_proposals.pending() == []  # it no longer blocks anything


def test_backfill_of_an_os_only_document_is_stated(world):
    doc_id = world.os_only()
    world.read(doc_id)
    world.intake()
    with world.svc.engine.begin() as conn:
        conn.execute(update(models.documents).where(models.documents.c.id == doc_id).values(
            status="confirmed", confirmed_at=func.now()))
        for name, v in HSSC.items():
            conn.execute(update(models.document_fields).where(
                models.document_fields.c.document_id == doc_id, models.document_fields.c.field == name
            ).values(value_confirmed=v))
    assert fact_proposals.backfill() == 1
    (row,) = world.rows()
    assert row.payload["document_ref"] == f"os:{doc_id}"
    assert delivered(world)["written"] == 1
    (candidate,) = world.candidates()
    assert "file_id" not in candidate.evidence and "authority" not in candidate.evidence


def test_a_corrected_confirmation_replaces_the_value_without_a_conflict_card(world):
    from app.memory.reconciler import MemoryReconciler
    from app.models import ProfileIssue
    from app.pai_c.memory import MemoryService

    doc_id = world.typed()
    world.read(doc_id)
    world.confirm(doc_id)
    delivered(world)
    with world.who.factory() as db:
        for c in db.scalars(select(MemoryCandidate)).all():
            assert MemoryReconciler(db).reconcile(c).accepted
        db.commit()
    world.confirm(doc_id, values={**HSSC, "marks_obtained": 910})
    assert delivered(world)["written"] == 1
    with world.who.factory() as db:
        for c in db.scalars(select(MemoryCandidate).where(MemoryCandidate.status == "pending")).all():
            assert MemoryReconciler(db).reconcile(c).accepted
        db.commit()
        (row,) = MemoryService(db).profile(world.id).records["education"]
        assert row["result"]["marks_obtained"] == 910 and db.scalars(select(ProfileIssue)).all() == []
