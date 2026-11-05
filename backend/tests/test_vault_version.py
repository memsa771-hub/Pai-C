"""P1-T4 Task 1 (R-13): each accepted Vault write that touches a StudentFacts key raises the student's Vault version
and, while the part is on, queues a `vault_event` outbox row valid for VaultEventV1. Flags off: nothing is written."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import MemoryCandidate, OsOutbox, VaultVersion
from app.os.contracts.vault_event import VaultEventV1
from app.pai_c.connect import vault_version
from scripts.counselor_eval_support import StudentSession

pytestmark = pytest.mark.req("R-13")


def facts_flag(value=True):
    return patch.object(config, "CONNECT_STUDENT_FACTS", value, create=True)


def part(value=True):
    return patch("app.pai_c.connect.outbox.part_on", return_value=value)


def write(db, ws, candidate_type, key, value, **kw):
    candidate = MemoryCandidateService(db).propose(
        ws, candidate_type, key=key, proposed_value=value, confidence=0.9, source_type="user_explicit",
        allow_user_explicit=True, input_channel="profile", evidence={"quote": "q", "capture": "details"}, **kw)
    result = MemoryReconciler(db).reconcile(candidate)
    assert result.accepted, result
    db.commit()
    return candidate


def version_row(db, ws):
    db.expire_all()
    return db.get(VaultVersion, ws)


def events(db, ws):
    db.expire_all()
    return list(db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == ws, OsOutbox.kind == "vault_event")
                           .order_by(OsOutbox.created_at, OsOutbox.key)))


def test_flag_off_writes_no_version_and_no_outbox():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        write(db, ws, "vault_item", "domicile", {"province": "punjab"})
        assert version_row(db, ws) is None and events(db, ws) == []


def test_flag_on_part_off_counts_but_queues_nothing():
    with StudentSession() as student, student.factory() as db, facts_flag(), part(False):
        ws = student.workspace_id
        write(db, ws, "vault_item", "domicile", {"province": "punjab"})
        assert version_row(db, ws).version == 1 and events(db, ws) == []


def test_one_write_gives_version_one_and_a_valid_event():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        write(db, ws, "vault_item", "domicile", {"province": "punjab"})
        row = version_row(db, ws)
        assert row.version == 1 and row.key_versions == {"constraint.domicile": 1}
        (event,) = events(db, ws)
        assert event.status == "pending" and event.key == f"vault_event:{ws}:1"
        checked = VaultEventV1.model_validate(event.payload)
        assert (checked.student_ref, checked.vault_version, checked.keys) == (ws, 1, ["constraint.domicile"])


def test_two_writes_give_versions_one_and_two_in_order():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        write(db, ws, "vault_item", "domicile", {"province": "punjab"})
        write(db, ws, "vault_fact", "finance.budget", {"band": "1_3_lakh"})
        row = version_row(db, ws)
        assert row.version == 2 and row.key_versions == {"constraint.domicile": 1, "constraint.budget": 2}
        assert [e.payload["vault_version"] for e in events(db, ws)] == [1, 2]
        assert events(db, ws)[1].payload["keys"] == ["constraint.budget"]


def test_a_write_that_touches_no_key_changes_nothing():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        write(db, ws, "vault_item", "interest", {"text": "Chess"})
        write(db, ws, "vault_fact", "identity.date_of_birth", "2008-01-02")
        assert version_row(db, ws) is None and events(db, ws) == []


def test_education_and_test_records_touch_their_keys():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        write(db, ws, "student_record", "education",
              {"qualification_name": "FSc", "institution_name": "A College", "academic_status": "completed",
               "result": {"marks_obtained": 900, "marks_total": 1100}})
        write(db, ws, "student_record", "test_attempt", {"test_type": "mdcat", "overall_score": "150"})
        keys = version_row(db, ws).key_versions
        assert keys["education.intermediate.marks_obtained"] == 1 and "education.intermediate.level" in keys
        assert keys["test.mdcat.score"] == 2


def test_keys_for_is_the_privacy_allow_list():
    def cand(kind, key, value=None, **kw):
        return MemoryCandidate(workspace_id="w", candidate_type=kind, key=key, operation="upsert",
                               proposed_value=value, **kw)

    assert vault_version.keys_for(cand("vault_item", "option", {"text": "Law", "status": "ruled_out"})) == [
        "constraint.excluded_fields"]
    assert vault_version.keys_for(cand("vault_item", "place_preference", {})) == ["preference.place"]
    assert vault_version.keys_for(cand("vault_item", "field_order", {})) == ["constraint.field_order"]
    assert vault_version.keys_for(cand("student_record", "education", {"qualification_name": "Bachelor"})) == [
        f"education.bachelor.{f}" for f in sorted(
            ["level", "marks_obtained", "marks_total", "percentage", "gpa", "gpa_scale", "grade",
             "part1.marks_obtained", "part1.marks_total", "part2.marks_obtained", "part2.marks_total"])]
    for kind, key in (("vault_fact", "identity.date_of_birth"), ("vault_fact", "identity.full_name"),
                      ("vault_fact", "contact.email"), ("vault_item", "family_member"),
                      ("student_record", "goal"), ("vault_item", "interest")):
        assert vault_version.keys_for(cand(kind, key, {"value": "x"})) == []
    assert vault_version.keys_for(cand("student_record", "education", {"qualification_name": "Other"})) == []


def test_a_failed_bump_is_not_swallowed():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        with patch.object(vault_version, "bump", side_effect=RuntimeError("lost")):
            with pytest.raises(RuntimeError):
                write(db, ws, "vault_item", "domicile", {"province": "punjab"})
        db.rollback()


def test_a_failed_outbox_call_keeps_the_write_and_the_version():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        with patch("app.pai_c.connect.outbox.record_vault_event", side_effect=RuntimeError("queue down")):
            write(db, ws, "vault_item", "domicile", {"province": "punjab"})
        assert version_row(db, ws).version == 1 and events(db, ws) == []


def test_a_retract_and_a_marks_patch_read_the_level_from_the_stored_record():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        first = write(db, ws, "student_record", "education",
                      {"qualification_name": "Bachelor", "institution_name": "U", "academic_status": "current"})
        record_id = db.get(MemoryCandidate, first.id).result_id
        patch_ = write(db, ws, "student_record", "education", {"result": {"gpa": 3.1, "gpa_scale": 4}},
                       entities={"record_id": record_id})
        assert vault_version.keys_for(patch_, db)[0].startswith("education.bachelor.")
        write(db, ws, "student_record", "education", None, operation="retract", entities={"record_id": record_id})
        assert version_row(db, ws).version == 3
        assert "education.bachelor.gpa" in version_row(db, ws).key_versions


@pytest.mark.req("R-80")
def test_a_part_only_edit_names_the_part_keys():
    with StudentSession() as student, student.factory() as db, facts_flag(), part():
        ws = student.workspace_id
        first = write(db, ws, "student_record", "education",
                      {"qualification_name": "fsc", "institution_name": "C", "academic_status": "completed"})
        record_id = db.get(MemoryCandidate, first.id).result_id
        patch_ = write(db, ws, "student_record", "education",
                       {"result": {"part1": {"marks_obtained": 400, "marks_total": 550}}},
                       entities={"record_id": record_id})
        keys = vault_version.keys_for(patch_, db)
        assert {"education.intermediate.part1.marks_obtained", "education.intermediate.part1.marks_total",
                "education.intermediate.part2.marks_obtained", "education.intermediate.part2.marks_total"} <= set(keys)
        versions = version_row(db, ws).key_versions
        assert versions["education.intermediate.part1.marks_obtained"] == 2
