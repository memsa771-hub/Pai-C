"""First-run onboarding: canonical writes, and the refinement trap it avoids.

The load-bearing test here is
`test_onboarding_category_does_not_freeze_the_living_status`. Under
`latest_wins` a `user_explicit` fact can never be superseded by conversation
extraction, so had onboarding written its dropdown answer into
`identity.current_status`, PAI would have been permanently unable to improve
"Student" into "Final-year BS Computer Science student". That is a silent,
ship-it-and-never-notice failure, so it gets an explicit test.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.memory.errors import MemoryDataError
from app.memory.field_definitions import VaultFieldDefinitionService, catalog_field_definitions
from app.memory.onboarding import ONBOARDING_FIELDS, OnboardingService
from app.memory.student_records import ENTITY_MODELS
from app.memory.vault import VaultService
from app.models import (
    BackgroundJob, EventRecord, FileRecord, MemoryCandidate, PaiEpisode, PaiMemory,
    ProfileIssue, StudentRecordRevision, User, VaultFact, VaultFieldDefinition, Workspace, VAULT_INTAKE_MODELS,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb(type_, compiler, **kw):
    return "JSON"


# Mirrors migrations 063 and 066 — one field of each sensitivity class, plus
# the two the onboarding flow introduces.
FIELD_SPECS = (
    ("preferences.preferred_language", "normal", None),
    ("identity.full_name", "sensitive", None),
    ("identity.preferred_name", "normal", None),
    ("identity.current_status", "normal", None),
    ("identity.nationality", "sensitive", None),
    ("identity.date_of_birth", "restricted", None),
    ("location.current_country", "normal", None),
    ("location.current_city", "normal", None),
    ("identity.gender", "sensitive", ["male", "female", "other", "undisclosed"]),
    ("identity.status_category", "normal", ["student", "professional", "other"]),
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _setup(connection, record):
        connection.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [User, Workspace, EventRecord, FileRecord, VaultFact, VaultFieldDefinition,
              MemoryCandidate, PaiMemory, PaiEpisode, ProfileIssue, StudentRecordRevision,
              BackgroundJob, *ENTITY_MODELS.values(), *VAULT_INTAKE_MODELS]
    Base.metadata.create_all(engine, tables=[m.__table__ for m in tables])

    with Session(engine, autoflush=False) as session:
        user = User(email="new@example.test", username="alikhan")
        session.add(user)
        session.flush()
        workspace = Workspace(name="Student", owner_user_id=user.id)
        session.add(workspace)
        session.flush()
        fields = VaultFieldDefinitionService(session)
        for spec in catalog_field_definitions():
            fields.upsert_definition(spec)
        for key, sensitivity, choices in FIELD_SPECS:
            schema = {"type": "string"}
            if choices:
                schema["enum"] = choices
            fields.upsert_definition({
                "key": key, "category": key.split(".")[0], "sensitivity": sensitivity,
                "data_type": "string", "validation_schema": schema,
                # Matches migration 063: restricted identifiers are review-gated.
                "conflict_policy": "manual_review" if sensitivity == "restricted" else "latest_wins",
            })
        session.commit()
        session.info.update(workspace=workspace, user=user)
        yield session
    engine.dispose()


ANSWERS = {
    "fullName": "Ali Ahmed",
    "preferredName": "Ali",
    "statusCategory": "student",
    "nationality": "Pakistani",
    "gender": "male",
    "dateOfBirth": "2003-04-15",
    "currentCountry": "Pakistan",
    "currentCity": "Islamabad",
}


def test_onboarding_is_required_until_it_is_completed(db):
    service = OnboardingService(db)
    workspace = db.info["workspace"]

    assert service.state(workspace)["required"] is True
    service.apply(workspace, ANSWERS)
    db.commit()

    state = service.state(workspace)
    assert state["required"] is False
    assert state["completedAt"]


def test_four_visible_cards_make_name_the_greeting_name(db):
    workspace = db.info['workspace']
    user = db.info['user']
    answers = {'fullName': 'Student Name', 'level': 'matric',
               'currentCity': 'Student City', 'replyLanguage': 'english'}
    result = OnboardingService(db).apply(workspace, answers)
    db.commit()
    assert result['completed'] and not result['rejected']
    assert user.display_name == 'Student Name'
    assert VaultService(db).snapshot(str(workspace.id), include_sensitive=True).get(
        'identity.preferred_name') is None


def test_answers_land_in_the_vault_as_first_hand_claims(db):
    workspace = db.info["workspace"]
    result = OnboardingService(db).apply(workspace, ANSWERS)
    db.commit()
    assert result["rejected"] == {}, result["rejected"]

    vault = VaultService(db)
    facts = vault.snapshot(str(workspace.id), include_sensitive=True)
    assert facts["identity.full_name"] == "Ali Ahmed"
    assert facts["identity.preferred_name"] == "Ali"
    assert facts["identity.status_category"] == "student"
    assert facts["identity.nationality"] == "Pakistani"
    assert facts["identity.gender"] == "male"
    assert facts["location.current_city"] == "Islamabad"

    # Provenance: these are the student's own words, not an inference.
    fact = vault.get_fact(str(workspace.id), "identity.full_name")
    assert fact.source_type == "user_explicit"
    assert fact.claim_origin == "student"
    assert fact.evidence["capture"] == "onboarding"


def test_review_gated_date_of_birth_applies_because_the_student_stated_it(db):
    """`manual_review` admits exactly one source — a first-hand statement."""
    workspace = db.info["workspace"]
    OnboardingService(db).apply(workspace, ANSWERS)
    db.commit()

    facts = VaultService(db).snapshot(str(workspace.id), include_sensitive=True)
    assert facts["identity.date_of_birth"] == "2003-04-15"
    # It applied outright rather than parking as something to confirm later.
    assert not db.query(ProfileIssue).filter_by(workspace_id=str(workspace.id)).count()


def test_onboarding_category_does_not_freeze_the_living_status(db):
    """The whole reason `identity.status_category` exists.

    Onboarding's coarse answer must not occupy `identity.current_status`,
    because a `user_explicit` fact there could never be refined by extraction.
    """
    workspace = db.info["workspace"]
    workspace_id = str(workspace.id)
    OnboardingService(db).apply(workspace, ANSWERS)
    db.commit()

    vault = VaultService(db)
    facts = vault.snapshot(workspace_id, include_sensitive=True)
    assert facts["identity.status_category"] == "student"
    assert "identity.current_status" not in facts, \
        "onboarding must leave current_status free for PAI to learn"

    # PAI later hears something richer in conversation — it must stick.
    vault.apply_fact(workspace_id, "identity.current_status",
                     "Final-year BS Computer Science student", "conversation")
    db.commit()
    refined = vault.snapshot(workspace_id, include_sensitive=True)
    assert refined["identity.current_status"] == "Final-year BS Computer Science student"
    assert refined["identity.status_category"] == "student"


def test_required_answers_are_enforced_and_nothing_is_half_written(db):
    workspace = db.info["workspace"]
    service = OnboardingService(db)
    with pytest.raises(MemoryDataError, match="statusCategory"):
        service.apply(workspace, {"fullName": "Ali Ahmed", "nationality": "Pakistani"})
    # Validation runs over the whole set first, so the valid answers in that
    # same submission were never written.
    assert VaultService(db).snapshot(str(workspace.id), include_sensitive=True) == {}
    assert service.state(workspace)["required"] is True


@pytest.mark.parametrize("answers,message", [
    ({"fullName": "A", "statusCategory": "astronaut"}, "statusCategory"),
    ({"fullName": "A", "statusCategory": "student", "gender": "yes"}, "gender"),
    ({"fullName": "A", "statusCategory": "student", "dateOfBirth": "15-04-2003"}, "dateOfBirth"),
    ({"fullName": "A", "statusCategory": "student", "dateOfBirth": "2099-01-01"}, "dateOfBirth"),
    ({"fullName": "A", "statusCategory": "student", "favouriteColour": "blue"}, "Unknown"),
])
def test_bad_answers_are_rejected_with_the_field_named(db, answers, message):
    with pytest.raises(MemoryDataError, match=message):
        OnboardingService(db).apply(db.info["workspace"], answers)


def test_returning_student_sees_their_own_values_prefilled(db):
    workspace = db.info["workspace"]
    service = OnboardingService(db)
    service.apply(workspace, ANSWERS)
    db.commit()

    prefill = service.state(workspace)["prefill"]
    assert prefill["fullName"] == "Ali Ahmed"
    assert prefill["statusCategory"] == "student"
    assert prefill["currentCity"] == "Islamabad"


def test_untouched_account_never_prefills_a_name_from_a_login_handle(db):
    prefill = OnboardingService(db).state(db.info["workspace"])["prefill"]
    assert "preferredName" not in prefill


def test_account_display_name_does_not_guess_legal_or_preferred_name(db):
    user = db.info["user"]
    user.display_name = "Ali Ahmed"
    db.commit()

    prefill = OnboardingService(db).state(db.info["workspace"])["prefill"]
    assert "fullName" not in prefill
    assert "preferredName" not in prefill


def test_every_identity_answer_is_required(db):
    state = OnboardingService(db).state(db.info["workspace"])
    assert state["fields"]
    # Only the marks of a record still being studied and the entry test are
    # optional (R-47 C7); every other question is required.
    optional = {(f["name"], f["labelKey"]) for f in state["fields"] if not f["required"]}
    assert optional == {("marksObtained", "marksSoFar"), ("marksTotal", None), ("grades", None),
                        ("entryTest", None), ("entryTestScore", "entryTestScore")}


def test_existing_equal_canonical_value_keeps_its_original_provenance(db):
    workspace = db.info["workspace"]
    workspace_id = str(workspace.id)
    vault = VaultService(db)
    vault.apply_fact(workspace_id, "location.current_city", "Islamabad", "conversation")
    db.commit()

    OnboardingService(db).apply(workspace, ANSWERS)
    db.commit()

    history = vault.history(workspace_id, "location.current_city")
    assert len(history) == 1
    assert history[0].source_type == "conversation"


def test_completing_onboarding_twice_keeps_the_first_timestamp(db):
    workspace = db.info["workspace"]
    service = OnboardingService(db)
    service.apply(workspace, ANSWERS)
    db.commit()
    first = service.state(workspace)["completedAt"]

    service.apply(workspace, {**ANSWERS, "currentCity": "Lahore"})
    db.commit()
    assert service.state(workspace)["completedAt"] == first
    # ...but a corrected answer still supersedes the old fact.
    facts = VaultService(db).snapshot(str(workspace.id), include_sensitive=True)
    assert facts["location.current_city"] == "Lahore"


def test_preferred_name_is_used_consistently_on_account_surfaces(db):
    workspace, user = db.info["workspace"], db.info["user"]
    assert user.display_name is None
    OnboardingService(db).apply(workspace, ANSWERS)
    db.commit()
    assert user.display_name == "Ali"

    OnboardingService(db).apply(workspace, {**ANSWERS, "preferredName": "A. Khan"})
    db.commit()
    assert user.display_name == "A. Khan"


def test_every_declared_field_maps_to_a_real_vault_key(db):
    """A question with no field definition would fail silently at reconcile."""
    fields = VaultFieldDefinitionService(db)
    for field in ONBOARDING_FIELDS:
        if field.record_field:
            assert field.field_key in ENTITY_MODELS
            assert hasattr(ENTITY_MODELS[field.field_key], field.record_field.split(".")[0])
        else:
            assert fields.get(field.field_key) is not None, field.field_key


THREE_STEPS = {"firstName": "Sam", "lastName": "Taylor", "level": "Secondary education",
               "status": "current", "dateOfBirth": "2008-03-12", "gender": "female",
               "currentCountry": "Pakistan", "currentCity": "My city"}


def test_three_step_form_is_advertised_in_order_with_no_reply_language(db):
    state = OnboardingService(db).state(db.info["workspace"])
    # Step 2 asks where the student lives first (the education step will
    # depend on the country), then date of birth and gender; step 3 is the
    # student's education alone.
    assert [(f["name"], f["step"]) for f in state["fields"]] == [
        ("firstName", 1), ("lastName", 1),
        ("currentCountry", 2), ("currentCity", 2), ("dateOfBirth", 2), ("gender", 2),
        ("level", 3), ("group", 3), ("group", 3),
        ("subjects", 3), ("subjects", 3), ("technology", 3), ("field", 3), ("field", 3),
        ("status", 3), ("year", 3), ("year", 3), ("year", 3), ("year", 3),
        ("marksObtained", 3), ("marksTotal", 3), ("marksObtained", 3), ("marksTotal", 3),
        ("grades", 3), ("grades", 3), ("matricMarksObtained", 3), ("matricMarksTotal", 3), ("oLevelGrades", 3),
        ("entryTest", 3), ("entryTestScore", 3)]
    assert "replyLanguage" not in {f["name"] for f in state["fields"]}
    # The default country is data, shown pre-selected for a new student.
    assert state["prefill"]["currentCountry"] == "Pakistan"


def test_three_step_form_composes_the_name_and_greets_by_first_name(db):
    workspace, user = db.info["workspace"], db.info["user"]
    service = OnboardingService(db)
    result = service.apply(workspace, THREE_STEPS)
    db.commit()
    assert result["completed"] and not result["rejected"]
    facts = VaultService(db).snapshot(str(workspace.id), include_sensitive=True)
    assert facts["identity.full_name"] == "Sam Taylor"
    # No separate preferred name: only first and last name are asked.
    assert "identity.preferred_name" not in facts
    assert facts["identity.date_of_birth"] == "2008-03-12"
    assert facts["identity.gender"] == "female"
    assert facts["location.current_country"] == "Pakistan"
    assert user.display_name == "Sam"
    prefill = service.state(workspace)["prefill"]
    assert (prefill["firstName"], prefill["lastName"]) == ("Sam", "Taylor")
    assert prefill["level"] == "Secondary education"


@pytest.mark.parametrize("missing", ["lastName", "dateOfBirth", "gender", "currentCity"])
def test_three_step_form_requires_every_answer(db, missing):
    answers = {k: v for k, v in THREE_STEPS.items() if k != missing}
    with pytest.raises(MemoryDataError, match=missing):
        OnboardingService(db).apply(db.info["workspace"], answers)


def test_a_retired_reply_language_answer_is_ignored_not_rejected(db):
    workspace = db.info["workspace"]
    result = OnboardingService(db).apply(workspace, {**THREE_STEPS, "replyLanguage": "english"})
    db.commit()
    assert result["completed"] and not result["rejected"]
    facts = VaultService(db).snapshot(str(workspace.id), include_sensitive=True)
    assert "preferences.preferred_language" not in facts


def test_entry_other_preserves_student_words_and_requests_catalog_review(db):
    from app.models import MemoryCandidate
    from sqlalchemy import select
    service=OnboardingService(db)
    workspace=db.info['workspace']
    service.apply(workspace,{'fullName':'A Student','level':'My education system','currentCity':'My city','replyLanguage':'english'})
    db.commit()
    candidate=db.scalar(select(MemoryCandidate).where(MemoryCandidate.workspace_id==workspace.id,MemoryCandidate.key=='education'))
    assert candidate.evidence['quote']=='My education system'
    assert candidate.evidence['catalog_review']['status']=='pending'
    assert next(f for f in service.state(workspace)['fields'] if f['name'] == 'level')['allowOther'] is True


def test_the_form_is_read_from_the_catalog(db):
    """No second field list: onboarding asks the catalog types marked `onboarding`."""
    from pathlib import Path
    from app.memory import onboarding
    from app.memory.catalog import vault_catalog
    assert not (Path(onboarding.__file__).parent / "entry_fields.json").exists()
    asked = sorted((t for t in vault_catalog().types() if t.onboarding), key=lambda t: t.onboarding["order"])
    keys = list(dict.fromkeys(f.field_key for f in ONBOARDING_FIELDS))
    assert keys == [t.key for t in asked]
    state = OnboardingService(db).state(db.info["workspace"])
    level = next(f for f in state["fields"] if f["name"] == "level")
    # The offered chips are catalog level codes; every one is a real code.
    codes = {c.code for c in vault_catalog().choices("levels")}
    assert level["choices"] == ["matric", "o_level", "intermediate", "a_level", "dae", "bachelor", "masters"]
    assert set(level["choices"]) <= codes


def test_a_level_chip_with_subjects_in_the_students_wording_needs_no_review(db):
    from app.models import MemoryCandidate
    from sqlalchemy import select
    workspace = db.info["workspace"]
    OnboardingService(db).apply(workspace, {**THREE_STEPS, "level": "o_level", "subjects": ["Maths"],
                                            "year": "year_1"})
    db.commit()
    candidate = db.scalar(select(MemoryCandidate).where(MemoryCandidate.workspace_id == workspace.id,
                                                        MemoryCandidate.key == "education"))
    assert candidate.proposed_value["value"] == {"qualification_name": "o_level", "academic_status": "current",
                                                 "details": {"subjects": ["mathematics"], "current_year": 1}}
    assert "catalog_review" not in candidate.evidence


def test_a_legacy_stored_level_prefills_as_its_catalog_chip(db):
    """Older rows hold "o-level" (the retired chip value); the prefill shows the
    catalog code so the chip is selected rather than an Other box."""
    from app.memory.student_records import ENTITY_MODELS
    workspace = db.info["workspace"]
    db.add(ENTITY_MODELS["education"](workspace_id=workspace.id, qualification_name="o-level",
                                       source_type="user_explicit", claim_origin="student",
                                       capture_method="onboarding"))
    db.commit()
    assert OnboardingService(db).state(workspace)["prefill"]["level"] == "o_level"


# -- Exact current education (EDUCATION_FOCUS_SPEC section 1) ----------------

# The marks of the record before the current one (R-47 C7): asked of an
# Intermediate or DAE student (Matric) and an A-level student (O-level), and
# required; dropped as hidden answers for every other level.
PRIOR = {"matricMarksObtained": "900", "matricMarksTotal": "1100", "oLevelGrades": "A B"}
PRIOR_LEVELS = ("matric", "o_level")
# The marks or grades a completed record requires.
COMPLETED_MARKS = {"marksObtained": "450", "marksTotal": "550", "grades": "A B"}
PERSON = {"firstName": "Sam", "lastName": "Taylor", "dateOfBirth": "2008-03-12", "gender": "female",
          "currentCountry": "Pakistan", "currentCity": "My city", **PRIOR}
STUDY_FIELDS = {"study_fields.bachelor": [("computer_science", "Computer Science"), ("mbbs", "MBBS (Medicine)")],
                "study_fields.master": [("computer_science", "Computer Science")]}


def _education_rows(db):
    from app.memory.student_records import StudentRecordService
    return StudentRecordService(db).list(str(db.info["workspace"].id), "education")


def _studied_rows(db):
    """The education rows other than the separate prior record (Matric or
    O-level) onboarding writes beside an Intermediate, DAE or A-level answer."""
    return [row for row in _education_rows(db) if row.qualification_name not in PRIOR_LEVELS]


def _education_candidates(db):
    from sqlalchemy import select
    from app.models import MemoryCandidate
    return db.scalars(select(MemoryCandidate).where(
        MemoryCandidate.workspace_id == db.info["workspace"].id, MemoryCandidate.key == "education")).all()


def _add_education(db, **values):
    from app.memory.student_records import ENTITY_MODELS
    db.add(ENTITY_MODELS["education"](workspace_id=db.info["workspace"].id, source_type="user_explicit",
                                       claim_origin="student", capture_method="onboarding", **values))
    db.commit()


def test_intermediate_pre_med_writes_fsc_record(db):
    result = OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "intermediate", "group": "pre_medical", "status": "current", "year": "year_2"})
    db.commit()
    assert result["completed"] and not result["rejected"], result
    # ONE record, through one candidate, holding every answer about it (the
    # prior Matric is its own record, through its own candidate).
    candidates = [c.proposed_value["value"]["qualification_name"] for c in _education_candidates(db)]
    assert sorted(candidates) == ["fsc", "matric"]
    [row] = _studied_rows(db)
    assert (row.qualification_name, row.field_of_study, row.academic_status) == ("fsc", "pre_medical", "current")
    assert row.details["current_year"] == 2
    assert row.graduation_year is None
    assert row.source_type == "user_explicit"


@pytest.mark.parametrize("group, level", [("pre_engineering", "fsc"), ("ics", "ics"), ("icom", "icom"),
                                          ("fa_humanities", "fa")])
def test_intermediate_groups_keep_todays_codes(db, group, level):
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, **COMPLETED_MARKS, "level": "intermediate", "group": group, "status": "completed", "year": "2025"})
    db.commit()
    [row] = _studied_rows(db)
    assert (row.qualification_name, row.field_of_study) == (level, group)
    assert (row.academic_status, row.graduation_year) == ("completed", 2025)


def test_a_level_subjects_saved(db):
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, **COMPLETED_MARKS, "level": "a_level", "subjects": ["physics", "mathematics", "chemistry"],
        "status": "completed", "year": "2024"})
    db.commit()
    [row] = _studied_rows(db)
    assert row.qualification_name == "a_level"
    assert row.details["subjects"] == ["physics", "mathematics", "chemistry"]
    assert (row.academic_status, row.graduation_year) == ("completed", 2024)
    prefill = OnboardingService(db).state(db.info["workspace"])["prefill"]
    assert prefill["subjects"] == ["physics", "mathematics", "chemistry"]
    assert (prefill["level"], prefill["status"], prefill["year"]) == ("a_level", "completed", "2024")


def test_subjects_are_read_against_the_levels_own_list(db):
    with pytest.raises(MemoryDataError, match="subjects"):
        OnboardingService(db).apply(db.info["workspace"], {
            **PERSON, "level": "o_level", "subjects": ["law"], "status": "current", "year": "year_1"})


@pytest.mark.parametrize("level", ["intermediate", "matric"])
def test_group_required_when_level_has_groups(db, level):
    with pytest.raises(MemoryDataError, match="group"):
        OnboardingService(db).apply(db.info["workspace"], {
            **PERSON, "level": level, "status": "current", "year": "year_1"})
    assert not _education_rows(db)
    assert VaultService(db).snapshot(str(db.info["workspace"].id), include_sensitive=True) == {}


def test_matric_group_is_the_field_of_study(db):
    service = OnboardingService(db)
    service.apply(db.info["workspace"], {**PERSON, "level": "matric", "group": "arts",
                                        "status": "current", "year": "year_1"})
    db.commit()
    [row] = _education_rows(db)
    assert (row.qualification_name, row.details["current_year"]) == ("matric", 1)
    # Read back as the matric chip, whatever the shared field normalised it to.
    assert service.state(db.info["workspace"])["prefill"]["group"] == "arts"


def test_dae_technology_is_the_field_of_study(db):
    OnboardingService(db).apply(db.info["workspace"], {**PERSON, "level": "dae", "technology": "electrical",
                                                      "status": "current", "year": "year_3"})
    db.commit()
    [row] = _studied_rows(db)
    assert (row.qualification_name, row.field_of_study, row.details["current_year"]) == ("dae", "electrical", 3)


def test_bachelor_field_comes_from_study_fields_and_asks_the_semester(db):
    service = OnboardingService(db, sources=STUDY_FIELDS)
    field = next(f for f in service.state(db.info["workspace"])["fields"]
                 if f["name"] == "field" and f["depends_on"]["values"] == ["bachelor"])
    assert field["choices"] == ["computer_science", "mbbs"]
    assert field["labels"]["mbbs"] == "MBBS (Medicine)" and field["searchable"]
    service.apply(db.info["workspace"], {**PERSON, "level": "bachelor", "field": "computer_science",
                                        "status": "current", "year": "semester_3"})
    db.commit()
    [row] = _education_rows(db)
    assert (row.qualification_name, row.field_of_study) == ("bachelor", "computer_science")
    # The semester is kept, and the year it falls in is what the rest of PAI reads.
    assert (row.details["current_semester"], row.details["current_year"]) == (3, 2)
    prefill = service.state(db.info["workspace"])["prefill"]
    assert (prefill["level"], prefill["field"], prefill["year"]) == ("bachelor", "computer_science", "semester_3")


def test_a_field_outside_the_study_fields_is_rejected(db):
    with pytest.raises(MemoryDataError, match="field"):
        OnboardingService(db, sources=STUDY_FIELDS).apply(db.info["workspace"], {
            **PERSON, "level": "masters", "field": "mbbs", "status": "current", "year": "year_1"})


@pytest.mark.parametrize("year", ["20", "2999", "year_1"])
def test_completed_year_must_be_a_real_past_year(db, year):
    with pytest.raises(MemoryDataError, match="year"):
        OnboardingService(db).apply(db.info["workspace"], {
            **PERSON, "level": "a_level", "subjects": ["physics"], "status": "completed", "year": year})


def test_other_level_needs_no_group(db):
    result = OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "My own school system", "status": "current"})
    db.commit()
    assert result["completed"] and not result["rejected"], result
    [row] = _education_rows(db)
    assert (row.qualification_name, row.academic_status, row.field_of_study) == (
        "My own school system", "current", None)


def test_answers_for_hidden_questions_are_dropped(db):
    """A group left over from a level the student changed away from never lands."""
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, **COMPLETED_MARKS, "level": "a_level", "group": "pre_medical", "subjects": ["biology"],
        "status": "completed", "year": "2023"})
    db.commit()
    [row] = _studied_rows(db)
    assert row.field_of_study is None


def test_legacy_fsc_prefill(db):
    """An `fsc` row with no group reads as Intermediate with the group unpicked,
    so the student must choose one to continue."""
    _add_education(db, qualification_name="fsc")
    prefill = OnboardingService(db).state(db.info["workspace"])["prefill"]
    assert prefill["level"] == "intermediate"
    assert "group" not in prefill and "status" not in prefill


def test_legacy_ics_record_prefills_its_group(db):
    _add_education(db, qualification_name="ics", academic_status="completed", graduation_year=2024)
    prefill = OnboardingService(db).state(db.info["workspace"])["prefill"]
    assert (prefill["level"], prefill["group"], prefill["status"], prefill["year"]) == (
        "intermediate", "ics", "completed", "2024")


def test_completing_a_legacy_fsc_record_keeps_one_education_record(db):
    _add_education(db, qualification_name="fsc")
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "intermediate", "group": "pre_engineering", "status": "current", "year": "year_1"})
    db.commit()
    [row] = _studied_rows(db)
    assert (row.qualification_name, row.field_of_study, row.academic_status) == (
        "fsc", "pre_engineering", "current")


def test_dependent_questions_are_advertised_with_their_condition(db):
    fields = OnboardingService(db).state(db.info["workspace"])["fields"]
    level = next(f for f in fields if f["name"] == "level")
    assert level["choices"] == ["matric", "o_level", "intermediate", "a_level", "dae", "bachelor", "masters"]
    assert level["depends_on"] is None and level["multi"] is False
    groups = [f for f in fields if f["name"] == "group"]
    assert [g["depends_on"] for g in groups] == [{"field": "level", "values": ["matric"]},
                                                 {"field": "level", "values": ["intermediate"]}]
    # General Science stays in the list for older data, but is not offered.
    assert groups[1]["choices"] == ["pre_engineering", "pre_medical", "ics", "icom", "fa_humanities"]
    subjects = [f for f in fields if f["name"] == "subjects"]
    assert all(s["multi"] for s in subjects) and len(subjects) == 2
    assert subjects[0]["labels"]["english_literature"] == "Literature in English"
    status = next(f for f in fields if f["name"] == "status")
    assert status["choices"] == ["current", "completed"] and status["depends_on"] == {"field": "level"}
    years = [f for f in fields if f["name"] == "year"]
    assert all(y["depends_on"]["field"] == "status" for y in years)
    assert any(y["isYear"] for y in years)


# -- Review round 1 -------------------------------------------------------------

@pytest.mark.parametrize("typed, chip", [
    ("Intermediate", "Intermediate"), ("FSc", "Intermediate"), ("inter", "Intermediate"),
    ("12th", "Intermediate"), ("ICS", "Intermediate"), ("BS", "Bachelor's"), ("bachelors", "Bachelor's"),
    ("SSC", "Matric"), ("O levels", "O-level"), ("igcse", "O-level"), ("A levels", "A-level"),
    ("MSc", "Master's"),
])
def test_other_text_that_names_a_level_points_to_its_chip(db, typed, chip):
    with pytest.raises(MemoryDataError, match=f"Choose {chip} above"):
        OnboardingService(db).apply(db.info["workspace"], {**PERSON, "level": typed, "status": "current"})
    assert not _education_rows(db)


@pytest.mark.parametrize("code", ["fsc", "ics", "icom", "fa"])
def test_retired_level_codes_are_not_accepted_directly(db, code):
    """The API takes chip codes (and Other's own words); Intermediate's codes
    come from its group, never from the level."""
    with pytest.raises(MemoryDataError, match="Choose Intermediate above"):
        OnboardingService(db).apply(db.info["workspace"], {**PERSON, "level": code, "status": "current"})


def test_other_and_the_level_wordings_are_advertised(db):
    service = OnboardingService(db)
    service.apply(db.info["workspace"], {**PERSON, "level": "other", "status": "current"})
    db.commit()
    assert _education_rows(db)[0].qualification_name == "other"
    level = next(f for f in service.state(db.info["workspace"])["fields"] if f["name"] == "level")
    # Normalised wordings -> the chip they mean, so the form says so before the form is sent.
    assert level["redirects"]["inter"] == "intermediate"
    assert level["redirects"]["bs"] == "bachelor"
    assert level["redirects"]["o levels"] == "o_level"
    assert "other" not in level["redirects"] and level["redirects"]["intermediate"] == "intermediate"
    assert level["labels"]["bachelor"] == "Bachelor's"


def test_matric_arts_is_stored_as_arts(db):
    OnboardingService(db).apply(db.info["workspace"], {**PERSON, **COMPLETED_MARKS, "level": "matric",
                                                      "group": "arts", "status": "completed", "year": "2024"})
    db.commit()
    [row] = _education_rows(db)
    assert row.field_of_study == "arts"


def test_legacy_general_science_leaves_the_group_to_pick(db):
    _add_education(db, qualification_name="fsc", field_of_study="general_science")
    prefill = OnboardingService(db).state(db.info["workspace"])["prefill"]
    assert prefill["level"] == "intermediate" and "group" not in prefill


def test_confirming_a_legacy_fsc_ics_record_updates_it(db):
    _add_education(db, qualification_name="fsc", field_of_study="ics", institution_name="Govt College")
    [legacy] = _education_rows(db)
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "intermediate", "group": "ics", "status": "current", "year": "year_2"})
    db.commit()
    [row] = _studied_rows(db)
    assert row.id == legacy.id
    assert (row.qualification_name, row.field_of_study, row.academic_status) == ("ics", "ics", "current")
    assert row.institution_name == "Govt College"


@pytest.mark.parametrize("value, shown", [
    ({"qualification_name": "matric", "field_of_study": "arts"}, "Arts"),
    ({"qualification_name": "matric", "field_of_study": "science_computer"}, "Science (Computer)"),
    ({"qualification_name": "dae", "field_of_study": "computer_information"}, "Computer Information Technology"),
    ({"qualification_name": "bachelor", "field_of_study": "software_engineering"}, "Software Engineering"),
    ({"qualification_name": "masters", "field_of_study": "data_science"}, "Data Science"),
    ({"qualification_name": "fsc", "field_of_study": "pre_medical"}, "Pre-Medical"),
])
def test_details_label_the_field_from_the_records_own_level(value, shown):
    from app.memory.catalog import vault_catalog
    from app.memory.vault_view import _display
    display = _display(vault_catalog().type("education"), value)
    assert shown in display and value["field_of_study"] not in display


# -- Review round 2: an in-place correction leaves nothing from the old answers --

def test_switching_to_studying_now_clears_the_graduation_year(db):
    _add_education(db, qualification_name="fsc", field_of_study="pre_medical", academic_status="completed",
                   graduation_year=2023)
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "intermediate", "group": "pre_medical", "status": "current", "year": "year_2"})
    db.commit()
    [row] = _studied_rows(db)
    assert (row.academic_status, row.graduation_year, row.details["current_year"]) == ("current", None, 2)


def test_switching_to_completed_clears_the_current_year_and_semester(db):
    _add_education(db, qualification_name="bachelor", field_of_study="computer_science",
                   academic_status="current", details={"current_semester": 3, "current_year": 2})
    OnboardingService(db, sources=STUDY_FIELDS).apply(db.info["workspace"], {
        **PERSON, "level": "bachelor", "field": "computer_science", "status": "completed", "year": "2025"})
    db.commit()
    [row] = _education_rows(db)
    assert (row.academic_status, row.graduation_year) == ("completed", 2025)
    assert "current_year" not in (row.details or {}) and "current_semester" not in (row.details or {})


def test_subjects_that_belong_to_no_question_of_the_level_are_cleared(db):
    """Subjects are an O/A-level answer: an Intermediate record corrected in
    place keeps none (here a legacy fsc row that carried subjects)."""
    _add_education(db, qualification_name="fsc", details={"subjects": ["physics", "chemistry"]})
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "intermediate", "group": "pre_engineering", "status": "current", "year": "year_1"})
    db.commit()
    [row] = _studied_rows(db)
    assert row.field_of_study == "pre_engineering" and "subjects" not in (row.details or {})


def test_leaving_o_level_keeps_its_subjects_off_the_new_level(db):
    """A different level is a different qualification: the O-level row keeps
    its subjects as history and the A-level record has only its own."""
    _add_education(db, qualification_name="o_level", academic_status="completed", graduation_year=2022,
                   details={"subjects": ["biology", "physics"]})
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "a_level", "subjects": ["mathematics"], "status": "current", "year": "year_1"})
    db.commit()
    rows = {row.qualification_name: row for row in _education_rows(db)}
    assert rows["a_level"].details["subjects"] == ["mathematics"] and rows["a_level"].graduation_year is None
    assert rows["o_level"].details["subjects"] == ["biology", "physics"]
    # The O-level grades asked beside A-level complete that same row (R-47 C7).
    assert len(_education_rows(db)) == 2 and rows["o_level"].result == {"grade": "A B"}


# -- R-47 C7: onboarding asks for marks ---------------------------------------

MARKS_QUESTIONS = ("marksObtained", "marksTotal", "grades", "matricMarksObtained", "matricMarksTotal",
                   "oLevelGrades", "entryTest", "entryTestScore")
INTERMEDIATE_WITH_MARKS = {
    **PERSON, "level": "intermediate", "group": "pre_medical", "status": "current", "year": "year_2",
    "marksObtained": "480", "marksTotal": "550", "matricMarksObtained": "950", "matricMarksTotal": "1100",
    "entryTest": "mdcat", "entryTestScore": "140"}


def _records(db, kind):
    from app.memory.student_snapshot import StudentSnapshotService
    return StudentSnapshotService(db).build(str(db.info["workspace"].id)).records[kind]


@pytest.mark.req("R-47")
def test_onboarding_state_lists_the_marks_questions(db):
    fields = OnboardingService(db).state(db.info["workspace"])["fields"]
    names = {f["name"] for f in fields}
    assert set(MARKS_QUESTIONS) <= names
    # The current-study marks question has its own label ("marks so far").
    assert "marksSoFar" in {f["labelKey"] for f in fields}
    assert next(f for f in fields if f["name"] == "marksObtained")["isNumber"] is True
    assert next(f for f in fields if f["name"] == "grades")["isText"] is True
    entry = next(f for f in fields if f["name"] == "entryTest")
    assert entry["required"] is False and entry["fieldKey"] == "test_attempt"
    assert entry["choices"] == ["mdcat", "ecat", "nat", "net", "sat"]


@pytest.mark.req("R-47")
def test_intermediate_marks_and_matric_marks_are_saved_stated(db):
    result = OnboardingService(db).apply(db.info["workspace"], INTERMEDIATE_WITH_MARKS)
    db.commit()
    assert result["rejected"] == {} and result["completed"], result
    education = {row["qualification_name"]: row for row in _records(db, "education")}
    assert set(education) == {"fsc", "matric"}
    assert education["fsc"]["academic_status"] == "current"
    assert education["fsc"]["result"] == {"marks_obtained": 480, "marks_total": 550}
    assert education["matric"]["academic_status"] == "completed"
    assert education["matric"]["result"] == {"marks_obtained": 950, "marks_total": 1100}
    [test] = _records(db, "test_attempt")
    assert test["test_type"] == "mdcat" and test["overall_score"] == "140"
    assert "status" not in (test.get("details") or {})
    for row in [*education.values(), test]:
        assert row["evidence_level"] == "stated" and row["source_type"] == "user_explicit"


@pytest.mark.req("R-47")
def test_marks_are_optional_while_studying(db):
    answers = {k: v for k, v in INTERMEDIATE_WITH_MARKS.items()
               if k not in ("marksObtained", "marksTotal", "entryTest", "entryTestScore")}
    result = OnboardingService(db).apply(db.info["workspace"], answers)
    db.commit()
    assert result["completed"] and not result["rejected"], result
    education = {row["qualification_name"]: row for row in _records(db, "education")}
    assert not education["fsc"].get("result")
    assert _records(db, "test_attempt") == []


@pytest.mark.req("R-47")
def test_completed_intermediate_requires_its_marks(db):
    answers = {**PERSON, "level": "intermediate", "group": "pre_medical", "status": "completed", "year": "2025",
               "matricMarksObtained": "950", "matricMarksTotal": "1100"}
    with pytest.raises(MemoryDataError, match="Missing required answer: .*marksObtained"):
        OnboardingService(db).apply(db.info["workspace"], answers)
    assert _education_rows(db) == []


@pytest.mark.req("R-47")
def test_prior_matric_marks_of_an_intermediate_student_are_required(db):
    answers = {k: v for k, v in INTERMEDIATE_WITH_MARKS.items() if not k.startswith("matric")}
    with pytest.raises(MemoryDataError, match="Missing required answer: .*matricMarksObtained"):
        OnboardingService(db).apply(db.info["workspace"], answers)


@pytest.mark.req("R-47")
def test_o_and_a_level_get_grades_not_marks(db):
    service = OnboardingService(db)
    workspace = db.info["workspace"]
    answers = {**PERSON, "level": "a_level", "subjects": ["physics"], "status": "completed", "year": "2025",
               "grades": " A* A  B ", "oLevelGrades": "3A* 4A",
               "marksObtained": "480", "marksTotal": "550", "matricMarksObtained": "950"}
    result = service.apply(workspace, answers)
    db.commit()
    assert result["completed"] and not result["rejected"], result
    education = {row["qualification_name"]: row for row in _records(db, "education")}
    assert education["a_level"]["result"] == {"grade": "A* A B"}
    assert education["o_level"]["result"] == {"grade": "3A* 4A"}
    assert education["o_level"]["academic_status"] == "completed"
    assert "matric" not in education
    prefill = service.state(workspace)["prefill"]
    assert (prefill["level"], prefill["grades"], prefill["oLevelGrades"]) == ("a_level", "A* A B", "3A* 4A")
    assert "marksObtained" not in prefill and "matricMarksObtained" not in prefill
    with pytest.raises(MemoryDataError, match="grades is too long"):
        service.apply(workspace, {**answers, "grades": "A" * 121})


@pytest.mark.req("R-47")
def test_marks_obtained_cannot_exceed_total(db):
    with pytest.raises(MemoryDataError, match="^marksObtained cannot be more than marksTotal$"):
        OnboardingService(db).apply(db.info["workspace"], {
            **INTERMEDIATE_WITH_MARKS, "marksObtained": "600", "marksTotal": "550"})
    with pytest.raises(MemoryDataError, match="^matricMarksObtained cannot be more than matricMarksTotal$"):
        OnboardingService(db).apply(db.info["workspace"], {
            **INTERMEDIATE_WITH_MARKS, "matricMarksObtained": "1101"})
    assert _education_rows(db) == [] and _records(db, "test_attempt") == []
    assert db.info["user"].onboarded_at is None


@pytest.mark.req("R-47")
@pytest.mark.parametrize("marks, message", [("9a5", "whole number"), ("-5", "whole number"),
                                            ("10000", "between 0 and 9999")])
def test_marks_must_be_a_whole_number_in_range(db, marks, message):
    with pytest.raises(MemoryDataError, match=f"marksObtained must be .*{message}"):
        OnboardingService(db).apply(db.info["workspace"], {**INTERMEDIATE_WITH_MARKS, "marksObtained": marks})


@pytest.mark.req("R-47")
def test_entry_test_without_score_is_planned(db):
    answers = {k: v for k, v in INTERMEDIATE_WITH_MARKS.items() if k != "entryTestScore"}
    OnboardingService(db).apply(db.info["workspace"], answers)
    db.commit()
    [test] = _records(db, "test_attempt")
    assert test["test_type"] == "mdcat" and test["details"]["status"] == "planned"
    assert "overall_score" not in test
    # The score given later corrects the same record, which is then no longer planned.
    OnboardingService(db).apply(db.info["workspace"], INTERMEDIATE_WITH_MARKS)
    db.commit()
    [test] = _records(db, "test_attempt")
    assert test["overall_score"] == "140" and "status" not in (test.get("details") or {})


@pytest.mark.req("R-47")
def test_prefill_after_prior_matric_record_keeps_intermediate(db):
    service = OnboardingService(db)
    workspace = db.info["workspace"]
    service.apply(workspace, {**INTERMEDIATE_WITH_MARKS, "status": "completed", "year": "2025"})
    db.commit()
    # The completed Matric record is written after the Intermediate one, so
    # it is the newest row; the form still opens on Intermediate.
    prefill = service.state(workspace)["prefill"]
    assert (prefill["level"], prefill["group"], prefill["status"]) == ("intermediate", "pre_medical", "completed")
    assert (prefill["marksObtained"], prefill["marksTotal"]) == ("480", "550")
    assert (prefill["matricMarksObtained"], prefill["matricMarksTotal"]) == ("950", "1100")
    assert (prefill["entryTest"], prefill["entryTestScore"]) == ("mdcat", "140")


@pytest.mark.req("R-47")
def test_reonboarding_corrects_existing_matric_record_in_place(db):
    service = OnboardingService(db)
    workspace = db.info["workspace"]
    service.apply(workspace, INTERMEDIATE_WITH_MARKS)
    db.commit()
    service.apply(workspace, {**INTERMEDIATE_WITH_MARKS, "matricMarksObtained": "960"})
    db.commit()
    rows = _education_rows(db)
    matric = [row for row in rows if row.qualification_name == "matric"]
    assert len(matric) == 1 and matric[0].result["marks_obtained"] == 960
    assert len(rows) == 2 and len(_records(db, "test_attempt")) == 1


@pytest.mark.req("R-47")
def test_an_existing_matric_row_takes_the_marks_in_place(db):
    """A student first onboarded at Matric, now at Intermediate: the matric
    marks complete that row rather than adding a second Matric record."""
    _add_education(db, qualification_name="matric", field_of_study="science_biology", academic_status="current",
                   details={"current_year": 2})
    OnboardingService(db).apply(db.info["workspace"], INTERMEDIATE_WITH_MARKS)
    db.commit()
    matric = [row for row in _education_rows(db) if row.qualification_name == "matric"]
    assert len(matric) == 1
    assert (matric[0].academic_status, matric[0].field_of_study, matric[0].result["marks_total"]) == (
        "completed", "science_biology", 1100)


@pytest.mark.req("R-47")
def test_a_test_the_form_does_not_offer_never_prefills_the_entry_test(db):
    """An IELTS record from chat is not an entry test: the form opens with
    no test picked, and choosing MDCAT adds its own record beside it."""
    from app.memory.student_records import ENTITY_MODELS
    workspace = db.info["workspace"]
    db.add(ENTITY_MODELS["test_attempt"](workspace_id=workspace.id, test_type="ielts", overall_score="7.5",
                                          source_type="user_explicit", claim_origin="student",
                                          capture_method="chat"))
    db.commit()
    service = OnboardingService(db)
    prefill = service.state(workspace)["prefill"]
    assert "entryTest" not in prefill and "entryTestScore" not in prefill
    service.apply(workspace, INTERMEDIATE_WITH_MARKS)
    db.commit()
    tests = {row["test_type"]: row for row in _records(db, "test_attempt")}
    assert (tests["ielts"]["overall_score"], tests["mdcat"]["overall_score"]) == ("7.5", "140")


# -- R-47 C7 fix round 1 -------------------------------------------------------

FIRST_ONLY = ("marksObtained", "marksTotal", "grades", "matricMarksObtained", "matricMarksTotal", "oLevelGrades")


def _required_by_name(state):
    """name -> required for each question; shared names are required if any variant is."""
    out = {}
    for f in state["fields"]:
        out[f["name"]] = out.get(f["name"], False) or f["required"]
    return out


@pytest.mark.req("R-47")
def test_completed_exam_marks_are_required_only_on_first_onboarding(db):
    service = OnboardingService(db)
    workspace = db.info["workspace"]
    first = _required_by_name(service.state(workspace))
    assert all(first[name] for name in FIRST_ONLY)
    service.apply(workspace, INTERMEDIATE_WITH_MARKS)
    db.commit()
    again = _required_by_name(service.state(workspace))
    assert not any(again[name] for name in FIRST_ONLY)
    # Every other question is still required once onboarded.
    assert again["level"] and again["group"] and again["status"] and again["firstName"]


@pytest.mark.req("R-47")
def test_reonboarding_without_prior_or_completed_marks_saves(db):
    service = OnboardingService(db)
    workspace = db.info["workspace"]
    service.apply(workspace, INTERMEDIATE_WITH_MARKS)
    db.commit()
    result = service.apply(workspace, {**PERSON, "level": "intermediate", "group": "pre_medical",
                                       "status": "completed", "year": "2025", "matricMarksObtained": "",
                                       "matricMarksTotal": ""})
    db.commit()
    assert result["completed"] and not result["rejected"], result
    education = {row["qualification_name"]: row for row in _records(db, "education")}
    assert education["fsc"]["academic_status"] == "completed"
    # The marks saved the first time are kept, not cleared.
    assert education["matric"]["result"] == {"marks_obtained": 950, "marks_total": 1100}


@pytest.mark.req("R-47")
def test_first_onboarding_still_requires_completed_exam_marks(db):
    answers = {**PERSON, "level": "matric", "group": "arts", "status": "completed", "year": "2024"}
    with pytest.raises(MemoryDataError, match="Missing required answer: marksObtained, marksTotal"):
        OnboardingService(db).apply(db.info["workspace"], answers)


@pytest.mark.req("R-47")
def test_field_state_sends_the_marks_checks(db):
    fields = OnboardingService(db).state(db.info["workspace"])["fields"]
    obtained = next(f for f in fields if f["name"] == "marksObtained")
    total = next(f for f in fields if f["name"] == "marksTotal")
    grades = next(f for f in fields if f["name"] == "grades")
    assert (obtained["atMost"], obtained["minimum"], obtained["maximum"]) == ("marksTotal", 0, 9999)
    assert (total["minimum"], total["maximum"]) == (1, 9999)
    assert next(f for f in fields if f["name"] == "matricMarksTotal")["minimum"] == 1
    assert grades["maxLength"] == 120 and obtained["maxLength"] is None


@pytest.mark.req("R-47")
@pytest.mark.parametrize("name", ["marksTotal", "matricMarksTotal"])
def test_a_total_of_zero_is_rejected(db, name):
    with pytest.raises(MemoryDataError, match=f"{name} must be between 1 and 9999"):
        OnboardingService(db).apply(db.info["workspace"], {**INTERMEDIATE_WITH_MARKS, name: "0"})


@pytest.mark.req("R-47")
def test_marks_so_far_need_their_total(db):
    answers = {k: v for k, v in INTERMEDIATE_WITH_MARKS.items() if k != "marksTotal"}
    with pytest.raises(MemoryDataError, match="^Missing required answer: marksTotal$"):
        OnboardingService(db).apply(db.info["workspace"], answers)
    assert _education_rows(db) == []
