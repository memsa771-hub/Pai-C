"""Stand-in Firebase ID tokens for tests that are not about Firebase itself.

`firebase_tokens({"token": identity})` makes the backend accept exactly those
bearer strings as those identities; any other bearer is rejected, as an
invalid Firebase token would be. The Auth emulator tests in
test_firebase_auth.py cover real token verification.
"""

from contextlib import contextmanager
from unittest.mock import patch

from app.security.identity import AuthenticatedIdentity


def identity_for(email: str, uid: str, *, verified: bool = True,
                 sign_in_provider: str = "google.com") -> AuthenticatedIdentity:
    return AuthenticatedIdentity("firebase", uid, email.lower(), verified, None, sign_in_provider)


@contextmanager
def firebase_tokens(tokens: dict):
    with patch("app.security.firebase_auth.verify_token", side_effect=lambda token: tokens.get(token)):
        yield


def link_owner(db, user, uid: str = "owner-uid") -> tuple[str, AuthenticatedIdentity]:
    """Give an existing test user a Firebase uid; returns (bearer, identity)."""
    user.firebase_uid = uid
    db.commit()
    return f"token-{uid}", identity_for(user.email, uid)
