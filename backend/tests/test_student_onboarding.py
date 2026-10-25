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
    Roadmap, RoadmapStudentState,
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
    tables.extend([Roadmap, RoadmapStudentState])
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
    assert all(field["required"] for field in state["fields"])


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
    # Step 2 is the student's education alone; date of birth and gender moved
    # beside the location so step 2 stays short on a phone.
    assert [(f["name"], f["step"]) for f in state["fields"]] == [
        ("firstName", 1), ("lastName", 1), ("level", 2), ("group", 2), ("group", 2),
        ("subjects", 2), ("subjects", 2), ("technology", 2), ("field", 2), ("field", 2),
        ("status", 2), ("year", 2), ("year", 2), ("year", 2), ("year", 2),
        ("dateOfBirth", 3), ("gender", 3), ("currentCountry", 3), ("currentCity", 3)]
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

PERSON = {"firstName": "Sam", "lastName": "Taylor", "dateOfBirth": "2008-03-12", "gender": "female",
          "currentCountry": "Pakistan", "currentCity": "My city"}
STUDY_FIELDS = {"study_fields.bachelor": [("computer_science", "Computer Science"), ("mbbs", "MBBS (Medicine)")],
                "study_fields.master": [("computer_science", "Computer Science")]}


def _education_rows(db):
    from app.memory.student_records import StudentRecordService
    return StudentRecordService(db).list(str(db.info["workspace"].id), "education")


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
    # ONE record, through one candidate, holding every education answer.
    assert len(_education_candidates(db)) == 1
    [row] = _education_rows(db)
    assert (row.qualification_name, row.field_of_study, row.academic_status) == ("fsc", "pre_medical", "current")
    assert row.details["current_year"] == 2
    assert row.graduation_year is None
    assert row.source_type == "user_explicit"


@pytest.mark.parametrize("group, level", [("pre_engineering", "fsc"), ("ics", "ics"), ("icom", "icom"),
                                          ("fa_humanities", "fa")])
def test_intermediate_groups_keep_todays_codes(db, group, level):
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "intermediate", "group": group, "status": "completed", "year": "2025"})
    db.commit()
    [row] = _education_rows(db)
    assert (row.qualification_name, row.field_of_study) == (level, group)
    assert (row.academic_status, row.graduation_year) == ("completed", 2025)


def test_a_level_subjects_saved(db):
    OnboardingService(db).apply(db.info["workspace"], {
        **PERSON, "level": "a_level", "subjects": ["physics", "mathematics", "chemistry"],
        "status": "completed", "year": "2024"})
    db.commit()
    [row] = _education_rows(db)
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
    [row] = _education_rows(db)
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
        **PERSON, "level": "a_level", "group": "pre_medical", "subjects": ["biology"],
        "status": "completed", "year": "2023"})
    db.commit()
    [row] = _education_rows(db)
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
    [row] = _education_rows(db)
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
    # Normalised wordings -> the chip they mean, so the form says so before step 3.
    assert level["redirects"]["inter"] == "intermediate"
    assert level["redirects"]["bs"] == "bachelor"
    assert level["redirects"]["o levels"] == "o_level"
    assert "other" not in level["redirects"] and level["redirects"]["intermediate"] == "intermediate"
    assert level["labels"]["bachelor"] == "Bachelor's"


def test_matric_arts_is_stored_as_arts(db):
    OnboardingService(db).apply(db.info["workspace"], {**PERSON, "level": "matric", "group": "arts",
                                                      "status": "completed", "year": "2024"})
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
    [row] = _education_rows(db)
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
    [row] = _education_rows(db)
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
    [row] = _education_rows(db)
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
