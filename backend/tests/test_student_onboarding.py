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
from app.memory.field_definitions import SEED_FIELD_DEFINITIONS, VaultFieldDefinitionService
from app.memory.onboarding import ONBOARDING_FIELDS, OnboardingService
from app.memory.student_profile_view import StudentProfileView
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
        for spec in SEED_FIELD_DEFINITIONS:
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
    answers = {'fullName': 'Student Name', 'level': 'fsc',
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


def test_profile_shows_onboarding_facts_including_the_students_own_date_of_birth(db):
    workspace = db.info["workspace"]
    OnboardingService(db).apply(workspace, ANSWERS)
    db.commit()

    profile = StudentProfileView(db).build(str(workspace.id), {"displayName": "Ali Ahmed"})
    assert profile["header"]["location"] == "Islamabad, Pakistan"
    # No richer status yet, so the header falls back to the category.
    assert profile["header"]["status"] == "Student"
    assert profile["facts"]["identity.gender"] == "male"
    # Date of birth is `restricted` in the Vault, but the student's own
    # Profile shows it back to them; no other restricted field is opened.
    assert profile["facts"]["identity.date_of_birth"] == "2003-04-15"


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
            assert hasattr(ENTITY_MODELS[field.field_key], field.record_field)
        else:
            assert fields.get(field.field_key) is not None, field.field_key


THREE_STEPS = {"firstName": "Sam", "lastName": "Taylor", "level": "Secondary education",
               "dateOfBirth": "2008-03-12", "gender": "female",
               "currentCountry": "Pakistan", "currentCity": "My city"}


def test_three_step_form_is_advertised_in_order_with_no_reply_language(db):
    state = OnboardingService(db).state(db.info["workspace"])
    assert [(f["name"], f["step"]) for f in state["fields"]] == [
        ("firstName", 1), ("lastName", 1), ("level", 2), ("dateOfBirth", 2), ("gender", 2),
        ("currentCountry", 3), ("currentCity", 3)]
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
