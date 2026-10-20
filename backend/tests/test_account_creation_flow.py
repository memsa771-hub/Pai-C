"""Account creation reaches PAI onboarding with no username at all."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.security.access import get_or_create_user
from app.database import Base
from app.models import AuthIdentity, User


def _session():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, AuthIdentity.__table__])
    return Session(engine, autoflush=False)


def test_new_accounts_never_get_a_username_even_if_one_is_offered():
    with _session() as db:
        user = get_or_create_user(db, {
            "email": "student@example.test",
            "supabase_uid": "signup-user",
            "username": "AliKhan",
        })
        assert user is not None
        assert user.username is None


def test_oauth_user_keeps_the_provider_name_and_stays_stable():
    claims = {"email": "new.student@example.test", "supabase_uid": "oauth-user-123",
              "display_name": "Sam Taylor"}
    with _session() as db:
        first = get_or_create_user(db, claims)
        assert first is not None and first.username is None
        assert first.display_name == "Sam Taylor"
        db.commit()

        again = get_or_create_user(db, claims)
        assert again is not None and again.id == first.id


def test_legacy_username_is_left_untouched_and_never_generated():
    with _session() as db:
        db.add(User(email="old@example.test", supabase_uid="old-user", username="oldhandle"))
        db.add(User(email="legacy@example.test", supabase_uid="legacy-user"))
        db.commit()

        old = get_or_create_user(db, {"email": "old@example.test", "supabase_uid": "old-user"})
        legacy = get_or_create_user(db, {"email": "legacy@example.test", "supabase_uid": "legacy-user"})
        assert old is not None and old.username == "oldhandle"
        assert legacy is not None and legacy.username is None
