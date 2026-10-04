"""Revocable Placement AI sessions, independent of the identity provider."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import config
from app.models import PaiSession, User

COOKIE_NAME = "pai_session"
TOKEN_PREFIX = "pai_"


def _now():
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(("pai-session-v1:" + token).encode()).hexdigest()


def _provider_hash(token: str) -> str:
    return hashlib.sha256(("supabase-access-v1:" + token).encode()).hexdigest()


def provider_token_was_revoked(db, provider_token: str) -> bool:
    return db.execute(select(PaiSession.id).where(
        PaiSession.provider_token_hash == _provider_hash(provider_token),
        PaiSession.revoked_at.isnot(None),
    ).limit(1)).first() is not None


def create_session(db, user: User, *, provider: str,
                   provider_token: str | None = None) -> str:
    token = TOKEN_PREFIX + secrets.token_urlsafe(48)
    now = _now()
    db.add(PaiSession(
        user_id=user.id, token_hash=_hash(token), provider=provider,
        provider_token_hash=_provider_hash(provider_token) if provider_token else None,
        created_at=now, last_seen_at=now,
        expires_at=now + timedelta(seconds=config.PAI_SESSION_TTL_SECONDS),
    ))
    db.flush()
    return token


def resolve_session(db, token: str) -> tuple[PaiSession, User] | None:
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 160:
        return None
    row = db.execute(select(PaiSession, User).join(
        User, User.id == PaiSession.user_id).where(
        PaiSession.token_hash == _hash(token),
        PaiSession.revoked_at.is_(None),
        PaiSession.expires_at > _now(),
    )).first()
    return (row[0], row[1]) if row else None


def revoke_session(db, token: str) -> bool:
    resolved = resolve_session(db, token)
    if not resolved:
        return False
    resolved[0].revoked_at = _now()
    db.flush()
    return True


def cookie_options() -> dict:
    return {
        "key": COOKIE_NAME, "httponly": True,
        "secure": config.APP_ENV.lower() == "production",
        "samesite": "lax", "path": "/",
        "max_age": config.PAI_SESSION_TTL_SECONDS,
    }
