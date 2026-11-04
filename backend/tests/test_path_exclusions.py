"""A field the student excluded in chat stays dismissed (R-47 C1): the matching
path is dismissed with the student's words, never suggested again, and PAI
says so once. Fake models only."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.jobs.service import JobDeferred
from app.models import BackgroundJob, CounselorTurnDecision, EventRecord, PaiPossibility, VaultItem
from app.pai_c.memory import MemoryService
from app.pai_c.paths import exclusions
from app.pai_c.paths.analyzer import enqueue_path_analysis, path_analysis_job
from app.pai_c.paths.fields import study_fields
from app.pai_c.possibilities import PossibilityService
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import fake_post
from tests.test_path_analyzer import add_education, analysis, path, seed

pytestmark = pytest.mark.req("R-47")

FSC_MEDICAL = {"qualification_name": "fsc", "field_of_study": "pre_medical", "academic_status": "current"}


def title(key):
    return study_fields()[key].title


def setup(student, db):
    turn, journey, _ = seed(student, db)
    add_education(student, db, FSC_MEDICAL)
    return turn, journey


def add_path(db, student, journey, key, status="suggested"):
    row = PossibilityService(db).add(student.workspace_id, journey.id, title=title(key), why="Earlier run",
                                     kind="discovered", source="analyzer", status=status)
    row.study_field = {"key": key, "isced": study_fields()[key].isced, "needs_check": False, "needs_group": []}
    db.commit()
    return row


def option(db, student, text, *, status="ruled_out", level="stated", quote=None, id=None):
    row = VaultItem(workspace_id=student.workspace_id, item_type="option",
                    value={"text": text, "status": status}, level=level, source_type="conversation",
                    evidence={"quote": quote} if quote else {}, **({"id": id} if id else {}))
    db.add(row)
    db.commit()
    return row


def notice_jobs(db, workspace_id):
    return db.scalars(select(BackgroundJob).where(BackgroundJob.workspace_id == workspace_id,
                                                  BackgroundJob.job_type == exclusions.JOB_PATHS_EXCLUDED)).all()


async def run_paths(db, student, turn, reply):
    """One quiet path run whose model returns `reply`; returns what was sent."""
    job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                   channel=None, reason="vault")
    db.commit()
    sent = []

    async def model(**kwargs):
        sent.append(kwargs["messages"][0]["content"])
        return json.dumps(reply)

    with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(side_effect=model)):
        result = await path_analysis_job(db.get(BackgroundJob, job_id), db)
    return result, sent


def test_ruled_out_option_dismisses_matching_path_with_student_words():
    with StudentSession() as student, student.factory() as db:
        _, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        excluded = option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        changed = exclusions.apply_exclusions(db, student.workspace_id)
        assert [r.id for r in changed] == [row.id]
        db.commit()
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        assert row.status == "dismissed"
        assert row.dismissal["reason"] == "student_excluded"
        assert row.dismissal["item_id"] == excluded.id
        assert row.dismissal["quote"] == "Pharm-D nahi karni"
        assert row.dismissal["at"]


@pytest.mark.parametrize("status", ["saved", "exploring"])
def test_saved_and_exploring_paths_are_dismissed_too(status):
    with StudentSession() as student, student.factory() as db:
        _, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d", status=status)
        option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        assert [r.id for r in exclusions.apply_exclusions(db, student.workspace_id)] == [row.id]
        assert row.status == "dismissed"


def test_chosen_path_is_left_alone():
    with StudentSession() as student, student.factory() as db:
        _, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d", status="chosen")
        option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        assert exclusions.apply_exclusions(db, student.workspace_id) == []
        assert row.status == "chosen" and row.dismissal is None


def test_exclusion_matching_no_field_changes_nothing():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        rows = [add_path(db, student, journey, "pharm_d"), add_path(db, student, journey, "mbbs", status="saved")]
        option(db, student, "Something else entirely", quote="Something else entirely nahi")
        assert exclusions.excluded_fields(db, student.workspace_id) == {}
        assert exclusions.apply_exclusions(db, student.workspace_id) == []
        assert [r.status for r in rows] == ["suggested", "saved"]
        assert notice_jobs(db, student.workspace_id) == []


@pytest.mark.parametrize("level,status", [("inferred", "ruled_out"), ("stated", "considering")])
def test_inferred_or_considering_option_changes_nothing(level, status):
    with StudentSession() as student, student.factory() as db:
        _, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        option(db, student, "Pharm-D", status=status, level=level, quote="Pharm-D")
        assert MemoryService(db).ruled_out_options(student.workspace_id) == []
        assert exclusions.apply_exclusions(db, student.workspace_id) == []
        assert row.status == "suggested" and row.dismissal is None


@pytest.mark.asyncio
async def test_restored_path_is_not_dismissed_again():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        excluded = option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        exclusions.apply_exclusions(db, student.workspace_id)
        db.commit()
        restored, changed = PossibilityService(db).transition(student.workspace_id, row.id, "save")
        db.commit()
        assert changed and restored.status == "saved"
        assert restored.dismissal["restored_at"] and restored.dismissal["item_id"] == excluded.id
        assert exclusions.apply_exclusions(db, student.workspace_id) == []
        # An unrelated Vault write (another option) runs the hook again.
        from app.memory.candidates import MemoryCandidateService
        from app.memory.reconciler import MemoryReconciler
        candidate = MemoryCandidateService(db).propose(workspace_id=student.workspace_id, candidate_type="vault_item",
            key="option", proposed_value={"text": "MBBS", "status": "considering"}, confidence=0.9,
            source_type="user_explicit", evidence={"quote": "MBBS soch raha hoon"}, allow_user_explicit=True)
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()
        assert db.get(PaiPossibility, row.id).status == "saved"
        # The next path run sees the restored path as the student's and keeps it.
        result, sent = await run_paths(db, student, turn, analysis(path("pharm_d")))
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        assert row.status == "saved" and row.dismissal["restored_at"]
        assert result["status"] == "stored" and row.id in result["paths"]
        assert '"key":"pharm_d"' in sent[0]
        assert notice_jobs(db, student.workspace_id) == []


def test_new_exclusion_after_restore_dismisses_again():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        first = option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        rows = exclusions.apply_exclusions(db, student.workspace_id)
        first_notice = exclusions.enqueue_exclusion_notice(db, student.workspace_id, rows,
                                                           source_event_id=turn.source_event_id)
        db.get(BackgroundJob, first_notice).status = "succeeded"
        PossibilityService(db).transition(student.workspace_id, row.id, "explore")
        db.commit()
        assert row.status == "exploring"
        first.status = "superseded"
        later = option(db, student, "Pharm-D", quote="Nahi, Pharm-D bilkul nahi")
        rows = exclusions.apply_exclusions(db, student.workspace_id)
        assert [r.id for r in rows] == [row.id]
        assert row.status == "dismissed"
        assert row.dismissal["item_id"] == later.id and "restored_at" not in row.dismissal
        assert row.dismissal["quote"] == "Nahi, Pharm-D bilkul nahi"
        # The new exclusion is a new notice, not the finished one from before.
        second_notice = exclusions.enqueue_exclusion_notice(db, student.workspace_id, rows,
                                                            source_event_id=turn.source_event_id)
        db.commit()
        assert second_notice and second_notice != first_notice
        assert db.get(BackgroundJob, second_notice).status == "pending"
        assert len(notice_jobs(db, student.workspace_id)) == 2
        # Retrying the same exclusion reuses that job.
        assert exclusions.enqueue_exclusion_notice(db, student.workspace_id, rows,
                                                   source_event_id=turn.source_event_id) == second_notice


@pytest.mark.asyncio
async def test_path_dismissed_by_hand_then_excluded_and_restored_is_not_dismissed_again():
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        service = PossibilityService(db)
        service.transition(student.workspace_id, row.id, "dismiss")
        db.commit()
        assert row.dismissal is None
        candidate = MemoryCandidateService(db).propose(workspace_id=student.workspace_id, candidate_type="vault_item",
            key="option", proposed_value={"text": "Pharm-D", "status": "ruled_out"}, confidence=0.9,
            source_type="user_explicit", source_event_ids=[turn.source_event_id],
            evidence={"quote": "Pharm-D nahi karni"}, allow_user_explicit=True)
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        # Already dismissed: only marked with the exclusion, no second notice for it.
        assert row.status == "dismissed" and row.dismissal["reason"] == "student_excluded"
        assert notice_jobs(db, student.workspace_id) == []
        restored, _ = service.transition(student.workspace_id, row.id, "save")
        db.commit()
        assert restored.dismissal["restored_at"]
        # An unrelated Vault write runs the hook again.
        other = MemoryCandidateService(db).propose(workspace_id=student.workspace_id, candidate_type="vault_item",
            key="option", proposed_value={"text": "MBBS", "status": "considering"}, confidence=0.9,
            source_type="user_explicit", evidence={"quote": "MBBS soch raha hoon"}, allow_user_explicit=True)
        assert MemoryReconciler(db).reconcile(other).accepted
        db.commit()
        assert db.get(PaiPossibility, row.id).status == "saved"
        result, sent = await run_paths(db, student, turn, analysis(path("pharm_d")))
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        assert row.status == "saved" and row.id in result["paths"]
        assert '"key":"pharm_d"' in sent[0]
        assert notice_jobs(db, student.workspace_id) == []


@pytest.mark.asyncio
async def test_excluded_restored_dismissed_by_hand_then_excluded_by_another_option_is_restamped():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        service = PossibilityService(db)
        first = option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        assert [r.id for r in exclusions.apply_exclusions(db, student.workspace_id)] == [row.id]
        service.transition(student.workspace_id, row.id, "save")
        db.commit()
        assert row.dismissal["item_id"] == first.id and row.dismissal["restored_at"]
        service.transition(student.workspace_id, row.id, "dismiss")
        db.commit()
        # A different option now excludes the field (the latest one wins); the first is superseded.
        first.status = "superseded"
        second = option(db, student, "Pharm-D", quote="Nahi, Pharm-D bilkul nahi")
        assert exclusions.apply_exclusions(db, student.workspace_id) == []  # no transition, no notice
        db.commit()
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        assert row.status == "dismissed"
        assert row.dismissal["item_id"] == second.id and "restored_at" not in row.dismissal
        restored, _ = service.transition(student.workspace_id, row.id, "save")
        db.commit()
        assert restored.dismissal["item_id"] == second.id and restored.dismissal["restored_at"]
        # Neither an unrelated Vault write nor the next analyzer run dismisses it again.
        assert exclusions.apply_exclusions(db, student.workspace_id) == []
        db.commit()
        assert db.get(PaiPossibility, row.id).status == "saved"
        result, sent = await run_paths(db, student, turn, analysis(path("pharm_d")))
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        assert row.status == "saved" and row.id in result["paths"]
        assert notice_jobs(db, student.workspace_id) == []


@pytest.mark.asyncio
async def test_a_failing_exclusion_step_does_not_fail_the_path_run():
    with StudentSession() as student, student.factory() as db:
        turn, _ = setup(student, db)
        with patch("app.pai_c.paths.exclusions.apply_exclusions", side_effect=RuntimeError("boom")):
            result, _ = await run_paths(db, student, turn, analysis(path("mbbs")))
        assert result["status"] == "stored"
        assert [row.title for row in PossibilityService(db).list(student.workspace_id)] == [title("mbbs")]


@pytest.mark.asyncio
async def test_analyzer_never_suggests_an_excluded_field():
    with StudentSession() as student, student.factory() as db:
        turn, _ = setup(student, db)
        option(db, student, "Biotechnology", quote="Biotech mere liye nahi")
        result, sent = await run_paths(db, student, turn, analysis(path("biotechnology"), path("mbbs")))
        db.expire_all()
        rows = PossibilityService(db).list(student.workspace_id)
        assert [row.title for row in rows] == [title("mbbs")]
        fields = sent[0].split("<fields>")[1].split("</fields>")[0]
        assert '"biotechnology"' not in fields and '"mbbs"' in fields
        assert notice_jobs(db, student.workspace_id) == []


def test_reconciler_hook_dismisses_and_queues_one_notice():
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        row = add_path(db, student, journey, "pharm_d")
        for _ in range(2):
            candidate = MemoryCandidateService(db).propose(workspace_id=student.workspace_id,
                candidate_type="vault_item", key="option", proposed_value={"text": "Pharm-D", "status": "ruled_out"},
                confidence=0.9, source_type="user_explicit", source_event_ids=[turn.source_event_id],
                evidence={"quote": "Pharm-D nahi karni"}, allow_user_explicit=True)
            assert MemoryReconciler(db).reconcile(candidate).accepted
            db.commit()
        db.expire_all()
        row = db.get(PaiPossibility, row.id)
        assert row.status == "dismissed" and row.dismissal["quote"] == "Pharm-D nahi karni"
        jobs = notice_jobs(db, student.workspace_id)
        assert len(jobs) == 1
        assert jobs[0].payload == {"possibility_ids": [row.id], "source_event_id": turn.source_event_id}


async def _dismissed(db, student, journey, keys):
    rows = [add_path(db, student, journey, key) for key in keys]
    for key in keys:
        option(db, student, "Pharm-D" if key == "pharm_d" else title(key), quote=f"{key} nahi")
    changed = exclusions.apply_exclusions(db, student.workspace_id)
    assert {r.id for r in changed} == {r.id for r in rows}
    return rows


def _messages(db, workspace_id):
    return db.scalars(select(EventRecord).where(EventRecord.network_id == workspace_id,
                                                EventRecord.source == "openagents:pai")).all()


@pytest.mark.asyncio
async def test_exclusion_notice_posts_the_fixed_sentence_once():
    notice = exclusions.policy()["notice"]
    for keys, expected in ((["pharm_d"], notice["one"].format(titles="Pharm-D (Pharmacy)")),
                           (["pharm_d", "medical_lab_technology"],
                            notice["other"].format(titles="Pharm-D (Pharmacy) and Medical Laboratory Technology"))):
        with StudentSession() as student, student.factory() as db:
            turn, journey = setup(student, db)
            rows = await _dismissed(db, student, journey, keys)
            job_id = exclusions.enqueue_exclusion_notice(db, student.workspace_id, rows,
                                                         source_event_id=turn.source_event_id)
            db.commit()
            job = db.get(BackgroundJob, job_id)
            with patch("app.pai_c.paths.exclusions.send_to_student",
                       AsyncMock(side_effect=fake_post(student))) as post:
                first = await exclusions.paths_excluded_job(job, db)
                again = await exclusions.paths_excluded_job(job, db)
            assert first["status"] == again["status"] == "posted"
            assert first["message_id"] == again["message_id"] and post.await_count == 1
            [message] = _messages(db, student.workspace_id)
            assert message.payload["content"] == expected
            assert message.target == turn.channel
            assert message.metadata_ == {"paths_excluded_job_id": job.id}


@pytest.mark.asyncio
async def test_exclusion_notice_waits_for_care():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        rows = await _dismissed(db, student, journey, ["pharm_d"])
        job_id = exclusions.enqueue_exclusion_notice(db, student.workspace_id, rows,
                                                     source_event_id=turn.source_event_id)
        db.add(CounselorTurnDecision(workspace_id=student.workspace_id, source_event_id=turn.source_event_id,
                                     source_timestamp=student.next_timestamp(), move="wellbeing",
                                     guard_violations=[]))
        db.commit()
        with patch("app.pai_c.paths.exclusions.send_to_student",
                   AsyncMock(side_effect=fake_post(student))) as post, pytest.raises(JobDeferred):
            await exclusions.paths_excluded_job(db.get(BackgroundJob, job_id), db)
        assert post.await_count == 0 and _messages(db, student.workspace_id) == []
