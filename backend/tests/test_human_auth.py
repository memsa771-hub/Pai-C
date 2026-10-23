"""The human-identity boundary on top of Firebase verification (stand-in tokens)."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User
from app.security.errors import EmailNotVerified
from app.security.human_auth import verify_identity_claims, verify_identity_token
from tests.auth_fakes import firebase_tokens, identity_for


@pytest.fixture
def database():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__])
    factory = sessionmaker(bind=engine, autoflush=False)
    with patch("app.database.SessionLocal", factory):
        yield factory


def test_first_verified_request_creates_the_account_and_returns_it(database):
    tokens = {"t": identity_for("Student@Example.test", "uid-1", sign_in_provider="password")}
    with firebase_tokens(tokens):
        claims = verify_identity_claims("t")
        again = verify_identity_claims("t")
    assert claims["session_user_id"] == again["session_user_id"]
    assert claims["email"] == "student@example.test" and claims["firebase_uid"] == "uid-1"
    with database() as db:
        assert db.query(User).count() == 1


def test_unverified_email_password_account_is_refused_with_its_own_error(database):
    tokens = {"t": identity_for("late@example.test", "uid-2", verified=False, sign_in_provider="password")}
    with firebase_tokens(tokens), pytest.raises(EmailNotVerified):
        verify_identity_claims("t")
    with database() as db:
        assert db.query(User).count() == 0


def test_invalid_token_resolves_to_nobody(database):
    with firebase_tokens({}):
        assert verify_identity_claims("forged") is None
        assert verify_identity_token("forged") is None
