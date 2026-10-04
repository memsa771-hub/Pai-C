"""PAI session authority, revocation, and legacy account linkage."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuthIdentity, PaiSession, User
from app.security.access import AuthAccountConflict, get_or_create_user
from app.security.app_session import (
    _hash, cookie_options, create_session, provider_token_was_revoked,
    resolve_session, revoke_session,
)


class PaiSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, AuthIdentity.__table__, PaiSession.__table__,
        ])
        self.db = Session(self.engine)
        self.user = User(email="student@example.test", supabase_uid="subject-a", username="student")
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_opaque_hashed_cookie_and_restore(self):
        first = create_session(self.db, self.user, provider="supabase", provider_token="jwt-a")
        second = create_session(self.db, self.user, provider="supabase", provider_token="jwt-b")
        self.db.commit()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 50)
        row = self.db.execute(select(PaiSession).where(PaiSession.token_hash == _hash(first))).scalar_one()
        self.assertNotEqual(row.token_hash, first)
        self.assertEqual(resolve_session(self.db, first)[1].id, self.user.id)
        self.assertIsNone(resolve_session(self.db, "jwt-a"))
        self.assertTrue(cookie_options()["httponly"])
        self.assertEqual(cookie_options()["samesite"], "lax")
        self.assertEqual(cookie_options()["path"], "/")
        with patch("app.security.app_session.config.APP_ENV", "production"):
            self.assertTrue(cookie_options()["secure"])

    def test_logout_blocks_session_and_provider_jwt_replay(self):
        token = create_session(self.db, self.user, provider="supabase", provider_token="jwt-a")
        self.db.commit()
        self.assertFalse(provider_token_was_revoked(self.db, "jwt-a"))
        self.assertTrue(revoke_session(self.db, token))
        self.db.commit()
        self.assertIsNone(resolve_session(self.db, token))
        self.assertTrue(provider_token_was_revoked(self.db, "jwt-a"))
        self.assertFalse(revoke_session(self.db, token))

    def test_expired_session_rejected(self):
        token = create_session(self.db, self.user, provider="supabase")
        session, _ = resolve_session(self.db, token)
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()
        self.assertIsNone(resolve_session(self.db, token))

    def test_stable_subject_preserves_account_when_email_changes(self):
        original_id = self.user.id
        claims = {"email": "new@example.test", "supabase_uid": "subject-a"}
        resolved = get_or_create_user(self.db, claims)
        self.db.commit()
        self.assertEqual(resolved.id, original_id)
        self.assertEqual(resolved.email, "new@example.test")
        identity = self.db.execute(select(AuthIdentity)).scalar_one()
        self.assertEqual(identity.user_id, original_id)
        self.assertEqual(identity.provider_subject, "subject-a")

    def test_same_email_different_subject_cannot_take_account(self):
        with self.assertRaises(AuthAccountConflict):
            get_or_create_user(self.db, {
                "email": "student@example.test", "supabase_uid": "subject-b",
            })

    def test_future_provider_uses_same_account_contract_without_supabase_uid(self):
        user = get_or_create_user(self.db, {
            "provider": "future-provider", "subject": "future-subject",
            "email": "future@example.test",
        })
        self.db.commit()
        self.assertIsNone(user.supabase_uid)
        identity = self.db.execute(select(AuthIdentity).where(
            AuthIdentity.provider == "future-provider")).scalar_one()
        self.assertEqual(identity.user_id, user.id)


if __name__ == "__main__":
    unittest.main()
