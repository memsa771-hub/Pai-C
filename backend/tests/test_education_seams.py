"""The seams between the education doors and the paths (final review of the
education-focus branch): an education change re-runs the paths, education
written by chat, documents or Other is readable, the Details editor offers the
level's own list, and the student's latest answer wins. Fake models only."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.memory.catalog import vault_catalog
from app.memory.errors import MemoryDataError
from app.memory.student_records import StudentRecordService
from app.models import BackgroundJob, Workspace
from app.pai_c.paths.analyzer import JOB_ANALYZE_PATHS, enqueue_path_analysis, path_analysis_job, policy
from app.pai_c.paths.fields import candidate_fields, current_education, student_groups, study_fields
from scripts.counselor_eval_support import StudentSession
from tests.test_path_fields import FA, again, by_title, run, reply_with, set_education, title

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
PERSON = {"firstName": "Sam", "lastName": "Taylor", "dateOfBirth": "2008-03-12", "gender": "female",
          "currentCountry": "Pakistan", "currentCity": "My city"}


def _jobs(db, workspace_id):
    return db.scalars(select(BackgroundJob).where(
        BackgroundJob.workspace_id == workspace_id, BackgroundJob.job_type == JOB_ANALYZE_PATHS)).all()


def _finish(db, workspace_id):
    """What the worker records once a job ran."""
    for job in _jobs(db, workspace_id):
        if job.status == "pending":
            job.status = "succeeded"
    db.commit()


# ---- Important 1: an education change re-runs the paths -------------------

@pytest.mark.asyncio
async def test_education_change_queues_a_new_run_that_prunes_the_old_group():
    with StudentSession() as student, student.factory() as db:
        await run(student, db, reply_with("mbbs", "bds"))
        [first] = _jobs(db, student.workspace_id)
        _finish(db, student.workspace_id)
        assert enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None,
                                     reason="student") == first.id  # nothing changed: the same job
        set_education(student, db, FA)
        again_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None,
                                         reason="student")
        db.commit()
        assert again_id != first.id
        with patch("app.pai_c.paths.analyzer.chat_completion",
                   AsyncMock(return_value=json.dumps(reply_with("bba")))):
            await path_analysis_job(db.get(BackgroundJob, again_id), db)
        db.expire_all()
        assert title("mbbs") not in by_title(student, db) and title("bba") in by_title(student, db)


def test_onboarding_education_write_queues_path_analysis():
    from app.routers.vault import _onboarding
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        _onboarding(db).apply(workspace, {**PERSON, "level": "intermediate", "group": "pre_medical",
                                          "status": "current", "year": "year_1"})
        db.commit()
        [job] = _jobs(db, student.workspace_id)
        assert job.payload["reason"] == "education"


def test_vault_education_edit_queues_path_analysis():
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.main import app
    with StudentSession() as student, student.factory() as db, \
         patch("app.security.access.verify_identity_claims",
               side_effect=lambda bearer: {"session_user_id": student.user_id}):
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            headers = {"X-Workspace-Token": "synthetic-test-only", "Authorization": "Bearer owner"}
            url = f"/v1/vault/entries?network={student.workspace_id}"
            saved = client.post(url, headers=headers, json={"type": "education", "value": {
                "qualification_name": "fsc", "field_of_study": "pre_medical", "academic_status": "current"}})
            assert saved.status_code == 200, saved.text
            assert len(_jobs(db, student.workspace_id)) == 1
            _finish(db, student.workspace_id)
            record_id = saved.json()["data"]["id"]
            edited = client.patch(f"/v1/vault/entries/record/{record_id}?network={student.workspace_id}",
                                  headers=headers, json={"value": {
                                      "qualification_name": "fa", "academic_status": "current"}})
            assert edited.status_code == 200, edited.text
            assert len(_jobs(db, student.workspace_id)) == 2  # the education changed: a new run
            client.post(url, headers=headers, json={"type": "interest", "value": {"text": "Robotics"}})
            assert len(_jobs(db, student.workspace_id)) == 2  # not an education write
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---- Important 2: readable education from any door ------------------------

@pytest.mark.parametrize("qualification, field, expected", [
    ("FSc Pre-Engineering", None, ("fsc", "pre_engineering")),
    ("BS Computer Science", None, ("bachelor", "computer_science")),
    ("Bachelor of Engineering", None, ("bachelor", None)),
    ("Bachelor of Science in Computer Science", None, ("bachelor", "computer_science")),
    ("MS", "Computer Science", ("masters", "computer_science")),
    ("Intermediate", "Computer Science", ("ics", None)),
    ("ICS", "Computer Science", ("ics", None)),
    ("fsc", "pre_medical", ("fsc", "pre_medical")),
    ("Matric", "Arts", ("matric", "arts")),
    ("Hafiz-e-Quran", None, (None, None)),
])
def test_education_is_read_from_any_wording(qualification, field, expected):
    assert vault_catalog().read_education(qualification, field) == expected


def test_paths_read_the_reviewers_shapes():
    assert student_groups({"qualification_name": "FSc Pre-Engineering"}) == {"pre_engineering"}
    assert student_groups({"qualification_name": "Intermediate", "field_of_study": "Computer Science"}) == {"ics"}
    assert candidate_fields({"qualification_name": "BS Computer Science"})["data_science"].standing == "open"
    assert candidate_fields({"qualification_name": "Bachelor of Engineering"}) == {}
    masters = candidate_fields({"qualification_name": "MS", "field_of_study": "Computer Science"})
    assert masters and "data_science" in masters


def test_masters_students_see_only_their_own_family():
    masters = candidate_fields({"qualification_name": "masters", "field_of_study": "computer_science"})
    family = study_fields()["computer_science"].family
    assert masters and all(c.field.family == family and c.standing == "open" for c in masters.values())
    assert "electrical_engineering" not in masters


def test_other_text_that_names_a_level_and_group_points_to_the_chip():
    from app.routers.vault import _onboarding
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        with pytest.raises(MemoryDataError, match="Choose Intermediate above"):
            _onboarding(db).apply(workspace, {**PERSON, "level": "FSc Pre-Engineering"})
        with pytest.raises(MemoryDataError, match="Choose Bachelor's above"):
            _onboarding(db).apply(workspace, {**PERSON, "level": "BS Computer Science"})


def _coverage(records):
    from types import SimpleNamespace
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.understanding.views import coverage_areas
    rows = [{"id": f"e{i}", "evidence": {"quote": "x"}, **values} for i, values in enumerate(records)]
    story = {"id": "t", "evidence": {"quote": "x"}, "test_type": "MDCAT"}
    return coverage_areas(CounselorNotebookData(), SimpleNamespace(
        facts={}, records={"education": rows, "test_attempt": [story]}))["history"]["covered"]


def test_history_is_covered_only_by_a_readable_group_or_field():
    assert not _coverage([{"qualification_name": "fsc", "academic_status": "current"}])
    assert not _coverage([{"qualification_name": "Current qualification"}])
    assert _coverage([{"qualification_name": "fsc", "field_of_study": "pre_engineering", "academic_status": "current"}])
    assert _coverage([{"qualification_name": "FSc Pre-Engineering"}])
    rule = json.loads((BACKEND / "app/pai_c/understanding/areas.json").read_text(encoding="utf-8"))["history"]
    assert rule["requires"] == ["readable_education"]


@pytest.mark.asyncio
async def test_chat_requested_analysis_says_what_it_needs():
    with StudentSession() as student, student.factory() as db:
        result, call, _, _ = await run(student, db, reply_with("mbbs"),
                                       education={"qualification_name": "fsc", "academic_status": "current"})
        assert result["status"] == "needs_education"
        call.assert_not_awaited()
        from app.models import EventRecord
        posted = db.scalars(select(EventRecord).where(EventRecord.network_id == student.workspace_id)).all()
        texts = [event.payload["content"] for event in posted if (event.metadata_ or {}).get("paths_job_id")]
        assert texts == [policy()["needs_education_messages"]["group"]]
        assert "Pre-Engineering" in texts[0] and "ICS" in texts[0]


@pytest.mark.asyncio
async def test_needs_education_is_decided_before_the_notebook_is_counted():
    from app.pai_c.possibilities import PossibilityService
    from app.journey import JourneyService
    with StudentSession() as student, student.factory() as db:
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        row = PossibilityService(db).add(student.workspace_id, journey.id, title=title("mbbs"), why="Earlier",
                                         kind="discovered", source="analyzer", status="suggested")
        row.study_field = {"key": "mbbs", "isced": "0912", "needs_check": False, "needs_group": []}
        db.commit()
        result, call = await again(student, db, reply_with("mbbs"))
        assert result["status"] == "needs_education"
        assert PossibilityService(db).list(student.workspace_id) == []


def test_extractor_writes_level_and_group_codes():
    from app.memory.extractor import SYSTEM_PROMPT
    assert "qualification_name is one level code" in SYSTEM_PROMPT
    assert "fsc + pre_engineering" in SYSTEM_PROMPT and "bachelor + computer_science" in SYSTEM_PROMPT
    assert "|".join(c.code for c in vault_catalog().choices("levels")) in SYSTEM_PROMPT
    assert "<choices" not in SYSTEM_PROMPT


# ---- Important 3: the Details editor follows the level ---------------------

def test_catalog_sends_the_level_lists_and_normalize_reads_them():
    from app.memory.normalize import normalize_candidate
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.main import app
    with StudentSession() as student, student.factory() as db, \
         patch("app.security.access.verify_identity_claims",
               side_effect=lambda bearer: {"session_user_id": student.user_id}):
        app.dependency_overrides[get_db] = lambda: db
        try:
            response = TestClient(app).get(f"/v1/vault/catalog?network={student.workspace_id}", headers={
                "X-Workspace-Token": "synthetic-test-only", "Authorization": "Bearer owner"})
        finally:
            app.dependency_overrides.pop(get_db, None)
    education = next(t for t in response.json()["data"]["types"] if t["key"] == "education")
    bachelor = [c["code"] for c in education["choice_by_level"]["field_of_study"]["bachelor"]]
    assert "computer_science" in bachelor and "pre_medical" not in bachelor
    assert education["choice_by_level"]["field_of_study"]["matric"][0]["code"] == "science_biology"
    out = normalize_candidate("student_record", "education",
                              {"qualification_name": "BS", "field_of_study": "Computer Science"}).value
    assert out == {"qualification_name": "bachelor", "field_of_study": "computer_science"}
    assert normalize_candidate("student_record", "education", {
        "qualification_name": "Matric", "field_of_study": "Arts"}).value["field_of_study"] == "arts"


# ---- Important 4: the latest answer wins -----------------------------------

def test_a_downward_correction_reads_as_the_latest_answer():
    from app.routers.vault import _onboarding
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        _onboarding(db).apply(workspace, {**PERSON, "level": "bachelor", "field": "computer_science",
                                          "status": "current", "year": "semester_1"})
        db.commit()
        _onboarding(db).apply(workspace, {**PERSON, "level": "intermediate", "group": "pre_engineering",
                                          "status": "current", "year": "year_2"})
        db.commit()
        rows = StudentRecordService(db).list(student.workspace_id, "education")
        values = [{"qualification_name": r.qualification_name, "field_of_study": r.field_of_study,
                   "academic_status": r.academic_status} for r in rows]
        # A higher level is never marked completed: that would claim a degree
        # the student never stated. The latest current record still wins.
        assert [v["academic_status"] for v in values] == ["current", "current"]
        assert current_education(values)["qualification_name"] == "fsc"
        prefill = _onboarding(db).state(workspace)["prefill"]
        assert prefill["level"] == "intermediate" and prefill["group"] == "pre_engineering"


def test_current_education_is_current_first_then_highest_completed():
    newest_completed = {"qualification_name": "matric", "academic_status": "completed"}
    older_completed = {"qualification_name": "bachelor", "academic_status": "completed"}
    current_low = {"qualification_name": "fsc", "academic_status": "current"}
    current_high = {"qualification_name": "bachelor", "academic_status": "current"}
    # Records arrive newest first, as StudentRecordService.list returns them.
    # No current record: the highest completed level wins (ruling, roadmap fix round 1),
    # ties go to the most recent.
    assert current_education([newest_completed, older_completed]) is older_completed
    newer_bachelor = dict(older_completed)
    assert current_education([newer_bachelor, older_completed]) is newer_bachelor
    planned = {"qualification_name": "bachelor", "academic_status": "planned"}
    assert current_education([planned]) is planned
    assert current_education([newest_completed, current_low, current_high]) is current_low
    assert current_education([]) is None


# ---- Minor 10: the path why is written to the student -----------------------

def test_path_why_is_written_in_the_second_person():
    from app.pai_c.deep.prompts import load_prompt
    prompt = load_prompt("path_analyzer")
    assert "second person" in prompt and "never \"the student's\"" in prompt
    doc = (ROOT / "docs/counselor/COUNSELOR_V3_PROMPTS.md").read_text(encoding="utf-8")
    assert prompt.strip() in doc


# ---- Re-review residuals ------------------------------------------------------

@pytest.mark.asyncio
async def test_going_back_to_an_earlier_education_is_a_fresh_run():
    with StudentSession() as student, student.factory() as db:
        await run(student, db, reply_with("mbbs"))
        [job_a] = _jobs(db, student.workspace_id)
        _finish(db, student.workspace_id)
        set_education(student, db, FA)
        job_b = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="student")
        db.commit()
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value=json.dumps(reply_with("bba")))):
            await path_analysis_job(db.get(BackgroundJob, job_b), db)
        db.expire_all()
        assert title("mbbs") not in by_title(student, db)
        _finish(db, student.workspace_id)
        set_education(student, db, {"qualification_name": "fsc", "field_of_study": "pre_medical",
                                    "academic_status": "current"})
        job_c = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="student")
        db.commit()
        assert len({job_a.id, job_b, job_c}) == 3
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value=json.dumps(reply_with("mbbs")))):
            await path_analysis_job(db.get(BackgroundJob, job_c), db)
        db.expire_all()
        assert title("mbbs") in by_title(student, db)


def test_a_field_outside_the_levels_list_is_refused_from_the_profile():
    from app.memory.normalize import normalize_candidate
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.main import app
    refused = normalize_candidate("student_record", "education", {
        "qualification_name": "bachelor", "field_of_study": "pre_medical"}, strict_choices=True)
    assert refused.rejected_reason and "Bachelor" in refused.rejected_reason
    # Chat and documents keep the student's words; the paths read them tolerantly.
    assert not normalize_candidate("student_record", "education", {
        "qualification_name": "bachelor", "field_of_study": "pre_medical"}).rejected_reason
    assert not normalize_candidate("student_record", "education", {
        "qualification_name": "bachelor", "field_of_study": ""}, strict_choices=True).rejected_reason
    with StudentSession() as student, student.factory() as db,          patch("app.security.access.verify_identity_claims",
               side_effect=lambda bearer: {"session_user_id": student.user_id}):
        app.dependency_overrides[get_db] = lambda: db
        try:
            response = TestClient(app).post(f"/v1/vault/entries?network={student.workspace_id}", headers={
                "X-Workspace-Token": "synthetic-test-only", "Authorization": "Bearer owner"},
                json={"type": "education", "value": {"qualification_name": "bachelor",
                                                     "field_of_study": "pre_medical"}})
        finally:
            app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 400 and "Bachelor" in response.json()["message"]


def test_an_old_level_wording_reads_its_levels_list():
    catalog = vault_catalog()
    spec = catalog.type("education")
    assert catalog.record_choice_fields(spec, {"qualification_name": "BS"})["field_of_study"] == "study_fields"
    assert catalog.record_choice_fields(spec, {"qualification_name": "BS Computer Science"})[
        "field_of_study"] == "study_fields"
    assert catalog.record_level(spec, {"qualification_name": "BS Computer Science"}) == "bachelor"


def test_details_entries_carry_the_records_level():
    from app.memory.vault_view import VaultView
    with StudentSession() as student, student.factory() as db:
        StudentRecordService(db).apply(student.workspace_id, "education",
                                       {"qualification_name": "BS Computer Science", "academic_status": "current"},
                                       source_type="user_explicit", claim_origin="student",
                                       capture_method="explicit_correction")
        db.commit()
        view = VaultView(db).build(student.workspace_id, include_sensitive=True)
        [entry] = [e for section in view["details"].values() for e in section["entries"] if e["type"] == "education"]
        assert entry["record_level"] == "bachelor"


def _onboard(db, workspace, **answers):
    from app.routers.vault import _onboarding
    _onboarding(db).apply(workspace, {**PERSON, "status": "current", **answers})
    db.commit()


def _statuses(db, workspace_id):
    return {r.qualification_name: r.academic_status for r in StudentRecordService(db).list(workspace_id, "education")}


def test_a_step_up_completes_the_lower_current_record():
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        _onboard(db, workspace, level="intermediate", group="pre_engineering", year="year_2")
        _onboard(db, workspace, level="bachelor", field="computer_science", year="semester_1")
        assert _statuses(db, student.workspace_id) == {"fsc": "completed", "bachelor": "current"}


def test_another_track_at_the_same_rank_is_left_alone():
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        _onboard(db, workspace, level="dae", technology="electrical", year="year_2")
        _onboard(db, workspace, level="a_level", subjects=["physics", "mathematics"], year="year_1")
        assert _statuses(db, student.workspace_id) == {"dae": "current", "a_level": "current"}


def test_a_higher_record_is_never_marked_completed():
    with StudentSession() as student, student.factory() as db:
        workspace = db.get(Workspace, student.workspace_id)
        _onboard(db, workspace, level="bachelor", field="computer_science", year="semester_1")
        _onboard(db, workspace, level="intermediate", group="pre_engineering", year="year_2")
        assert _statuses(db, student.workspace_id) == {"bachelor": "current", "fsc": "current"}
