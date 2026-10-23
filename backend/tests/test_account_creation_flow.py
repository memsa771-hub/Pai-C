"""Account creation and linking from a verified Firebase identity; no usernames."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User
from app.security.access import AuthAccountConflict, get_or_create_user


def _session():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__])
    return Session(engine, autoflush=False)


def _claims(email, uid, **extra):
    return {"provider": "firebase", "subject": uid, "email": email, **extra}


def test_new_accounts_never_get_a_username_even_if_one_is_offered():
    with _session() as db:
        user = get_or_create_user(db, _claims("student@example.test", "signup-user", username="AliKhan"))
        assert user is not None and user.username is None and user.firebase_uid == "signup-user"


def test_google_user_keeps_the_provider_name_and_stays_stable():
    claims = _claims("new.student@example.test", "google-user-123", display_name="Sam Taylor")
    with _session() as db:
        first = get_or_create_user(db, claims)
        assert first is not None and first.display_name == "Sam Taylor"
        db.commit()
        again = get_or_create_user(db, claims)
        assert again is not None and again.id == first.id


def test_existing_account_is_linked_once_and_keeps_its_data():
    with _session() as db:
        db.add(User(email="old@example.test", supabase_uid="old-supabase", username="oldhandle"))
        db.commit()
        linked = get_or_create_user(db, _claims("old@example.test", "firebase-old"))
        assert linked.firebase_uid == "firebase-old" and linked.username == "oldhandle"
        assert linked.supabase_uid == "old-supabase"
        db.commit()
        with pytest.raises(AuthAccountConflict):
            get_or_create_user(db, _claims("old@example.test", "someone-else"))


def test_only_firebase_identities_resolve():
    with _session() as db:
        assert get_or_create_user(db, {"provider": "supabase", "subject": "x", "email": "a@example.test"}) is None
        assert get_or_create_user(db, _claims("", "uid")) is None
