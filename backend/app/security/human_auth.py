# -*- coding: utf-8 -*-
"""The authentication boundary for human users.

Every protected request carries a Firebase ID token as its Bearer; nothing a
client sends about who it is (a user id, an email in a body) is ever trusted.
A verified token resolves to the PAI account linked by `users.firebase_uid`,
which is created on the first verified request. Email/password accounts must
have verified their address first (EmailNotVerified -> 403).
"""

import logging
from typing import Optional

from app.security.errors import EmailNotVerified
from app.security import firebase_auth

logger = logging.getLogger(__name__)


def verify_identity_claims(token: str) -> Optional[dict]:
    """Verify the bearer and resolve (or create) its PAI account."""
    identity = firebase_auth.verify_token(token)
    if identity is None:
        return None
    if identity.needs_email_verification:
        raise EmailNotVerified()
    from app.database import SessionLocal
    from app.security.access import AuthAccountConflict, get_or_create_user

    db = SessionLocal()
    try:
        user = get_or_create_user(db, {
            "provider": identity.provider, "subject": identity.subject,
            "email": identity.email, "display_name": identity.display_name,
        })
        if user is None:
            return None
        db.commit()
        return {
            "provider": identity.provider,
            "email": user.email,
            "firebase_uid": user.firebase_uid,
            "session_user_id": str(user.id),
            "display_name": user.display_name,
        }
    except AuthAccountConflict:
        db.rollback()
        logger.warning("human_auth: verified Firebase identity conflicts with another account")
        return None
    finally:
        db.close()


def verify_identity_token(token: str) -> Optional[str]:
    """Verify the bearer and return its account email."""
    claims = verify_identity_claims(token)
    return claims["email"] if claims else None
