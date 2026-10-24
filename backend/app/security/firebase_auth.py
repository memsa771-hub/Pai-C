# -*- coding: utf-8 -*-
"""Firebase Auth: the one human-identity provider (web, desktop, mobile).

The Admin SDK verifies Firebase ID tokens locally against Google's public
keys and mints the action codes behind our own verification and
password-reset emails. Firebase never sends an email itself: the links are
rebuilt on APP_URL and delivered through Resend (app.services.auth_emails).

With FIREBASE_AUTH_EMULATOR_HOST set (local tests), the SDK talks to the Auth
emulator and needs no service account.
"""

import logging
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import config
from app.infrastructure import cache
from app.security.errors import IdentityUnavailable
from app.security.identity import AuthenticatedIdentity

logger = logging.getLogger(__name__)

_APP_NAME = "pai-auth"
_lock = threading.Lock()
# ID tokens live an hour; after that a revoked session cannot refresh anyway.
_REVOCATION_TTL_SECONDS = 3600 + 300
_revoked_before: dict[str, int] = {}


class ResetLinkInvalid(Exception):
    """The reset link is used, expired or wrong."""


class WeakPassword(Exception):
    """Firebase refused the new password."""


def _app():
    import firebase_admin
    from firebase_admin import credentials

    with _lock:
        try:
            return firebase_admin.get_app(_APP_NAME)
        except ValueError:
            pass
        options = {"projectId": config.FIREBASE_PROJECT_ID} if config.FIREBASE_PROJECT_ID else None
        if os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
            cred = None
        elif config.FIREBASE_SERVICE_ACCOUNT:
            cred = credentials.Certificate(config.FIREBASE_SERVICE_ACCOUNT)
        else:
            raise IdentityUnavailable("Firebase Auth is not configured")
        return firebase_admin.initialize_app(cred, options, name=_APP_NAME)


def verify_token(token: str) -> AuthenticatedIdentity | None:
    """Verify a Firebase ID token; None when it is invalid, expired or revoked."""
    if not token or token.count(".") != 2:
        return None
    from firebase_admin import auth

    try:
        claims = auth.verify_id_token(token, app=_app(), clock_skew_seconds=10)
    except auth.CertificateFetchError as exc:
        # Google's keys were unreachable: we could not check, which is not a "no".
        raise IdentityUnavailable(str(exc)) from exc
    except (ValueError, auth.InvalidIdTokenError, auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError, auth.UserDisabledError):
        return None
    email = str(claims.get("email") or "").strip().lower()
    if not email or not claims.get("uid"):
        return None
    # Revoked: issued at or before the revocation (whole seconds, so the same second counts).
    if int(claims.get("iat") or 0) <= _sessions_valid_after(str(claims["uid"])):
        return None
    return AuthenticatedIdentity(
        provider="firebase", subject=str(claims["uid"]), email=email,
        email_verified=bool(claims.get("email_verified")),
        display_name=claims.get("name"),
        sign_in_provider=str((claims.get("firebase") or {}).get("sign_in_provider") or ""),
        auth_time=int(claims.get("auth_time") or 0), issued_at=int(claims.get("iat") or 0),
    )


def _revocation_key(uid: str) -> str:
    return f"pai:auth:sessions-valid-after:{uid}"


def _sessions_valid_after(uid: str) -> int:
    """Tokens issued at or before this moment were revoked (0: none). Shared through Redis."""
    stored = cache.get_bytes(_revocation_key(uid))
    return max(int(stored) if stored else 0, _revoked_before.get(uid, 0))


def revoke_sessions(uid: str) -> None:
    """Sign this account out everywhere: no refresh, and current ID tokens stop working now."""
    from firebase_admin import auth

    auth.revoke_refresh_tokens(uid, app=_app())
    now = int(time.time())
    _revoked_before[uid] = now
    cache.set_bytes(_revocation_key(uid), str(now).encode(), _REVOCATION_TTL_SECONDS)


def _identity_toolkit(method: str) -> str:
    emulator = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    base = f"http://{emulator}/identitytoolkit.googleapis.com" if emulator else "https://identitytoolkit.googleapis.com"
    return f"{base}/v1/accounts:{method}?key={config.FIREBASE_WEB_API_KEY or 'emulator'}"


def reset_password(code: str, new_password: str) -> str:
    """Use a reset link's code to set a new password, then end every session; returns the email."""
    from firebase_admin import auth

    try:
        response = httpx.post(_identity_toolkit("resetPassword"),
                              json={"oobCode": code, "newPassword": new_password}, timeout=10)
    except httpx.HTTPError as exc:
        raise IdentityUnavailable(str(exc)) from exc
    body = response.json() if response.content else {}
    if response.status_code != 200:
        message = str((body.get("error") or {}).get("message") or "")
        if message.startswith(("WEAK_PASSWORD", "PASSWORD_DOES_NOT_MEET_REQUIREMENTS")):
            raise WeakPassword(message)
        if message.startswith(("INVALID_OOB_CODE", "EXPIRED_OOB_CODE", "USER_DISABLED", "EMAIL_NOT_FOUND")):
            raise ResetLinkInvalid(message)
        raise IdentityUnavailable(f"Firebase resetPassword failed: {response.status_code} {message}")
    email = str(body.get("email") or "").strip().lower()
    revoke_sessions(auth.get_user_by_email(email, app=_app()).uid)
    return email


def disable_user(uid: str) -> None:
    """Turn the Firebase account off (kept, not deleted) and end its sessions; already gone is fine."""
    from firebase_admin import auth

    try:
        auth.update_user(uid, disabled=True, app=_app())
        revoke_sessions(uid)
    except auth.UserNotFoundError:
        pass


def _oob_code(link: str) -> str:
    code = parse_qs(urlparse(link).query).get("oobCode", [""])[0]
    if not code:
        raise IdentityUnavailable("Firebase returned an action link without a code")
    return code


def email_verification_code(email: str) -> str:
    """An action code that verifies this email; the link is ours to build."""
    from firebase_admin import auth

    try:
        return _oob_code(auth.generate_email_verification_link(email, app=_app()))
    except (auth.TooManyAttemptsTryLaterError, auth.UnexpectedResponseError) as exc:
        raise IdentityUnavailable(str(exc)) from exc


def password_reset_code(email: str) -> str | None:
    """An action code to reset this account's password, or None if no account uses it."""
    from firebase_admin import auth

    try:
        return _oob_code(auth.generate_password_reset_link(email, app=_app()))
    except (auth.UserNotFoundError, auth.EmailNotFoundError):
        return None
    except (auth.TooManyAttemptsTryLaterError, auth.UnexpectedResponseError) as exc:
        raise IdentityUnavailable(str(exc)) from exc
