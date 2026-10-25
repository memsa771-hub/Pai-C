"""Paths are real fields of study, filtered by the student's education, and
never padded: 0 to 5, each with real fit. Fake models only."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.memory.student_records import StudentRecordService
from app.models import BackgroundJob
from app.pai_c.paths.analyzer import (PathAnalysis, _card_text, enqueue_path_analysis,
                                      path_analysis_job, policy, sanitize)
from app.pai_c.paths.fields import candidate_fields, student_group, student_groups, study_fields
from app.pai_c.possibilities import PossibilityService
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_mirror import fake_post
from tests.test_path_analyzer import EVIDENCE, seed

FSC_MEDICAL = {"qualification_name": "fsc", "field_of_study": "pre_medical", "academic_status": "current"}
ICS = {"qualification_name": "ics", "academic_status": "current"}


def title(key):
    return study_fields()[key].title


def fit(label, status, ids=("c1",)):
    return {"label": label, "status": status, "note": "", "evidence_item_ids": list(ids)}


STRONG = [fit("Hands-on skill", "have"), fit("Maths", "partial", ["c3"])]


def path(field_key, *, title="Some wording the model chose", fits=STRONG, ids=("c1",)):
    return {"field_key": field_key, "title": title, "why": "It builds on what you said.",
            "evidence_item_ids": list(ids), "fit": list(fits)}


def analysis(*paths):
    return PathAnalysis.model_validate({"message": "Here are some fields.", "paths": list(paths)})


def add_education(student, db, values):
    StudentRecordService(db).apply(student.workspace_id, "education", values, source_type="user_explicit",
                                   claim_origin="student", capture_method="explicit_correction")
    db.commit()


async def run(student, db, reply, *, education=FSC_MEDICAL):
    turn, journey, _ = seed(student, db)
    if education:
        add_education(student, db, education)
    job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                   channel=turn.channel, reason="asked")
    db.commit()
    sent = []

    async def model(**kwargs):
        sent.append(kwargs["messages"][0]["content"])
        return json.dumps(reply)

    with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(side_effect=model)) as call, \
         patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock(side_effect=fake_post(student))):
        result = await path_analysis_job(db.get(BackgroundJob, job_id), db)
    db.expire_all()
    return result, call, sent, journey


# ---- candidates by education ------------------------------------------------

def test_group_filters_fields():
    candidates = candidate_fields(FSC_MEDICAL)
    assert candidates["mbbs"].standing == "open"
    assert candidates["electrical_engineering"].standing == "check"
    assert "computer_science" in candidates and candidates["computer_science"].standing == "check"
    assert "aerospace_engineering" not in candidates  # open to pre-engineering, check only for DAE
    result = sanitize(analysis(path("mbbs"), path("aerospace_engineering")), EVIDENCE, set(), candidates)
    assert [row["title"] for row in result] == [title("mbbs")]
    assert result[0]["study_field"]["key"] == "mbbs"
    assert result[0]["study_field"]["isced"] == study_fields()["mbbs"].isced
    assert result[0]["study_field"]["needs_check"] is False


def test_check_field_is_flagged():
    candidates = candidate_fields(ICS)
    assert candidates["software_engineering"].standing == "open"
    assert candidates["electrical_engineering"].standing == "check"
    result = sanitize(analysis(path("electrical_engineering"), path("software_engineering")),
                      EVIDENCE, set(), candidates)
    flags = {row["title"]: row["study_field"]["needs_check"] for row in result}
    assert flags == {title("electrical_engineering"): True, title("software_engineering"): False}


def test_unknown_field_dropped():
    candidates = candidate_fields(FSC_MEDICAL)
    raw = analysis(path("astrology"), path(""), path("mbbs", title="Medicine and surgery"))
    result = sanitize(raw, EVIDENCE, set(), candidates)
    # The saved title is the study field's, never the model's wording.
    assert [row["title"] for row in result] == [title("mbbs")]


def test_weak_fit_is_dropped_never_padded():
    rules = policy()
    assert rules["max_paths"] == 5 and rules["min_fit_evidence"] == 2
    candidates = candidate_fields(FSC_MEDICAL)
    weak = [fit("Interest", "have"), fit("Fees", "unknown", [])]
    uncited = [fit("Interest", "have", ["made-up"]), fit("Maths", "partial", ["made-up"])]
    blocked = [fit("Interest", "have"), fit("Fees", "blocker", ["c2"])]
    raw = analysis(path("mbbs", fits=weak), path("bds", fits=uncited), path("nursing", fits=blocked),
                   path("pharm_d"))
    assert [row["title"] for row in sanitize(raw, EVIDENCE, set(), candidates)] == [title("pharm_d")]


def test_count_is_capped_and_dismissed_fields_stay_gone():
    from app.pai_c.possibility_titles import normalized_title
    candidates = candidate_fields(FSC_MEDICAL)
    keys = ["mbbs", "bds", "pharm_d", "nursing", "zoology", "botany", "biotechnology"]
    result = sanitize(analysis(*[path(k) for k in keys]), EVIDENCE, {normalized_title(title("bds"))}, candidates)
    assert len(result) == 5 and title("bds") not in [row["title"] for row in result]


def test_matric_sees_every_field_with_the_group_it_needs():
    candidates = candidate_fields({"qualification_name": "matric", "field_of_study": "science"})
    assert set(candidates) == set(study_fields())
    mbbs = candidates["mbbs"]
    assert mbbs.standing == "needs_group" and mbbs.needs_group == ("pre_medical",)
    # Open to every intermediate group: no group to name.
    assert candidates["bba"].standing == "open" and candidates["bba"].needs_group == ()
    result = sanitize(analysis(path("mbbs")), EVIDENCE, set(), candidates)
    assert result[0]["study_field"]["needs_group"] == [{"code": "pre_medical", "label": "Pre-Medical"}]
    assert candidate_fields({"qualification_name": "o_level", "details": {"subjects": ["biology"]}})["mbbs"].standing == "needs_group"


def test_degree_students_see_their_family_open_and_the_rest_to_check():
    candidates = candidate_fields({"qualification_name": "bachelor", "field_of_study": "computer_science"})
    assert candidates["data_science"].standing == "open"
    assert candidates["mbbs"].standing == "check"
    assert candidate_fields({"qualification_name": "masters", "field_of_study": "Electrical Engineering"})[
        "civil_engineering"].standing == "open"


def test_dae_sees_fields_open_or_check_for_dae():
    candidates = candidate_fields({"qualification_name": "dae", "field_of_study": "electrical"})
    assert candidates["engineering_technology"].standing == "open"
    assert candidates["electrical_engineering"].standing == "check"
    assert "mbbs" not in candidates


@pytest.mark.parametrize("record", [None, {}, {"qualification_name": "other"},
                                    {"qualification_name": "Hafiz-e-Quran"},
                                    {"qualification_name": "fsc"},
                                    {"qualification_name": "bachelor"}])
def test_unknown_education_has_no_candidates(record):
    assert candidate_fields(record) == {}


def test_a_level_subjects_open_the_union_of_their_groups():
    record = {"qualification_name": "a_level",
              "details": {"subjects": ["biology", "chemistry", "physics", "mathematics"]}}
    assert student_groups(record) == {"pre_medical", "pre_engineering"}
    assert student_group(record) == "pre_medical"  # the old first-match answer still works
    candidates = candidate_fields(record)
    assert candidates["mbbs"].standing == candidates["electrical_engineering"].standing == "open"
    assert student_groups({"qualification_name": "a_level", "details": {"subjects": ["history"]}}) == {"fa_humanities"}


def test_education_evidence_shows_labels_not_codes():
    text = _card_text({"qualification_name": "fsc", "field_of_study": "pre_engineering",
                       "academic_status": "current", "canonical_level": "upper_secondary"}, "education")
    assert "pre_engineering" not in text and "upper_secondary" not in text and "fsc" not in text
    assert "FSc" in text and "Pre-Engineering" in text
    subjects = _card_text({"qualification_name": "a_level",
                           "details": {"subjects": ["computer_science", "mathematics"]}}, "education")
    assert "computer_science" not in subjects and "Computer Science" in subjects


# ---- the job ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_sends_only_candidates_and_stores_field_titles():
    with StudentSession() as student, student.factory() as db:
        result, call, sent, _ = await run(student, db, {"message": "Here are some fields.", "paths": [
            path("mbbs", title="Doctor"), path("electrical_engineering")]})
        assert result["status"] == "posted" and call.await_count == 1
        assert '"key":"mbbs"' in sent[0] and '"standing":"check"' in sent[0]
        assert "aerospace_engineering" not in sent[0] and "Computer use" not in sent[0]
        rows = {row.title: row for row in PossibilityService(db).list(student.workspace_id)}
        assert set(rows) == {title("mbbs"), title("electrical_engineering")}
        assert rows[title("electrical_engineering")].study_field["needs_check"] is True
        assert rows[title("mbbs")].study_field["key"] == "mbbs"
        for row in rows.values():
            for line in row.evidence:
                assert "pre_medical" not in line["text"] and "upper_secondary" not in line["text"]


@pytest.mark.asyncio
async def test_no_paths_without_education():
    with StudentSession() as student, student.factory() as db:
        result, call, _, _ = await run(student, db, {"message": "x", "paths": [path("mbbs")]}, education=None)
        assert result["status"] == "needs_education"
        call.assert_not_awaited()
        assert PossibilityService(db).list(student.workspace_id) == []


@pytest.mark.asyncio
async def test_zero_paths_allowed():
    from app.main import app
    from tests.test_counselor_mirror import client_for
    from tests.test_path_analyzer import HEADERS
    with StudentSession() as student, student.factory() as db:
        result, call, _, _ = await run(student, db, {"message": "Not enough yet.", "paths": [
            path("mbbs", fits=[fit("Interest", "have")])]})
        assert call.await_count == 1 and result["status"] == "no_paths"
        assert PossibilityService(db).list(student.workspace_id) == []
        client = client_for(student)
        try:
            listed = client.get(f"/v1/counselor/possibilities?network={student.workspace_id}", headers=HEADERS)
            assert listed.json()["data"]["possibilities"] == []  # the "PAI needs to know more" state
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_old_generic_paths_replaced():
    with StudentSession() as student, student.factory() as db:
        turn, journey, _ = seed(student, db)
        service = PossibilityService(db)
        old = service.add(student.workspace_id, journey.id, title="Computer use", why="Earlier",
                          kind="discovered", source="analyzer", status="suggested")
        kept = service.add(student.workspace_id, journey.id, title="Mechanics and metal trades", why="Earlier",
                           kind="discovered", source="analyzer", status="saved")
        gone = service.add(student.workspace_id, journey.id, title="Arts", why="Earlier",
                           kind="discovered", source="analyzer", status="dismissed")
        own = service.add(student.workspace_id, journey.id, title="Mobile repair", why="Mine",
                          kind="student_added", source="student", status="saved")
        old_id, kept_id, gone_id, own_id = old.id, kept.id, gone.id, own.id
        add_education(student, db, FSC_MEDICAL)
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                       channel=turn.channel, reason="asked")
        db.commit()
        reply = {"message": "Here are some fields.", "paths": [
            path("mbbs"), {"title": "Mobile repair", "why": "Yours.", "fit": [fit("Hands-on skill", "have")]}]}
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value=json.dumps(reply))), \
             patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock(side_effect=fake_post(student))):
            await path_analysis_job(db.get(BackgroundJob, job_id), db)
        db.expire_all()
        rows = {row.id: row for row in service.list(student.workspace_id)}
        assert old_id not in rows  # suggested generic path is removed
        assert rows[kept_id].status == "saved" and rows[kept_id].study_field == {"outdated": True}
        assert rows[gone_id].status == "dismissed" and rows[gone_id].study_field is None
        assert rows[own_id].study_field is None and rows[own_id].fit[0]["status"] == "have"
        assert title("mbbs") in {row.title for row in rows.values()}
