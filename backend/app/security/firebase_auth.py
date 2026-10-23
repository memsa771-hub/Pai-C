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
from urllib.parse import parse_qs, urlparse

from app.config import config
from app.security.errors import IdentityUnavailable
from app.security.identity import AuthenticatedIdentity

logger = logging.getLogger(__name__)

_APP_NAME = "pai-auth"
_lock = threading.Lock()


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
    return AuthenticatedIdentity(
        provider="firebase", subject=str(claims["uid"]), email=email,
        email_verified=bool(claims.get("email_verified")),
        display_name=claims.get("name"),
        sign_in_provider=str((claims.get("firebase") or {}).get("sign_in_provider") or ""),
    )


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
