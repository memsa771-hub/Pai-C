# -*- coding: utf-8 -*-
"""
Auth endpoints for provider identity exchange, PAI sessions, and usernames.

Supabase verifies credentials. PAI resolves a stable account and owns the
revocable application session used by protected workspace APIs.
"""

import logging
import ipaddress
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import config
from app.database import get_db
from app.security.human_auth import verify_identity_claims
from app.security.identity import SupabaseIdentityVerifier
from app.security.access import (
    AuthAccountConflict, extract_bearer, get_or_create_owned_workspace,
    get_or_create_user, resolve_current_user,
)
from app.security.app_session import (
    COOKIE_NAME, cookie_options, create_session, provider_token_was_revoked,
    resolve_session, revoke_session,
)
from app.models import User
from app.api.response import ResponseCode, json_response, success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

_USERNAME_MIN_LENGTH = 3
_USERNAME_MAX_LENGTH = 32


def _normalize_username(raw: str) -> Optional[str]:
    username = (raw or "").strip().lower()
    if not (_USERNAME_MIN_LENGTH <= len(username) <= _USERNAME_MAX_LENGTH):
        return None
    if not all(c.isalnum() or c in "_-" for c in username):
        return None
    return username


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
#
# Two independent budgets, because they stop different attacks:
#
#   username   a brute force against ONE account. The tight limit, and the one
#              that matters. Immune to every student sharing an address.
#   source     password spraying across many accounts, and username
#              enumeration. A deliberately loose backstop.
#
# ONLY FAILURES COUNT against the username budget, and a successful sign-in
# clears it. That is what makes a shared address safe. The previous version
# keyed solely on `request.client.host` and counted every attempt, successes
# included — so behind a load balancer or a campus NAT, where every student
# arrives from one address, twenty ordinary logins locked out everybody for an
# hour. There is no proxy-header configuration here, so that address is the
# proxy's in any real deployment.
#
# Redis shares these budgets across workers in deployed environments.
# When Redis is configured but unavailable, username auth fails closed.
# Bounded in-process buckets serve deployments without Redis.

_GENERIC_SIGN_IN_ERROR = "Invalid username or password"
_RATE_LIMITED_MESSAGE = "Too many attempts. Please try again later."

_SIGN_IN_WINDOW_SECONDS = 3600

# Hard ceiling on tracked keys, so a spray across a dictionary of usernames
# cannot grow this map without bound. Sweeping expired buckets is not enough on
# its own: during a fast spray every bucket is fresh, so nothing is expired and
# the sweep frees nothing — hence the eviction below.
_MAX_TRACKED_KEYS = 10_000

_budgets: dict = {}


def _prune(bucket: deque, now: float) -> None:
    while bucket and now - bucket[0] > _SIGN_IN_WINDOW_SECONDS:
        bucket.popleft()


def _over_budget(key: str, limit: int) -> bool:
    if config.REDIS_URL:
        from app.infrastructure.cache import _lazy_client, _sync_failed
        client = _lazy_client()
        if client is None:
            return True  # a configured shared limiter fails closed
        try:
            return int(client.get(f"pai:auth-rate:{key}") or 0) >= limit
        except Exception as exc:
            _sync_failed(exc)
            return True
    """Whether `key` is out of budget. Records nothing — see `_charge`."""
    bucket = _budgets.get(key)
    if bucket is None:
        return False
    _prune(bucket, time.monotonic())
    if not bucket:
        # A plain dict with an explicit delete, not a defaultdict: the old one
        # created and kept a bucket for every key merely looked at, including
        # usernames that do not exist.
        _budgets.pop(key, None)
        return False
    return len(bucket) >= limit


def _charge(key: str) -> None:
    if config.REDIS_URL:
        from app.infrastructure.cache import _lazy_client, _sync_failed
        client = _lazy_client()
        if client is None:
            return
        try:
            redis_key = f"pai:auth-rate:{key}"
            client.incr(redis_key)
            client.expire(redis_key, _SIGN_IN_WINDOW_SECONDS, nx=True)
        except Exception as exc:
            _sync_failed(exc)
        return
    now = time.monotonic()
    if len(_budgets) >= _MAX_TRACKED_KEYS and key not in _budgets:
        _evict(now)
    bucket = _budgets.setdefault(key, deque())
    _prune(bucket, now)
    bucket.append(now)


def _evict(now: float) -> None:
    """Make room: drop expired keys, then the least recently charged.

    Eviction forgets a key's accumulated failures, which fails OPEN for that
    one account — so it is deliberately last-touched order, which is the
    attacker's own throwaway keys, and only reachable by a caller who is
    already past the source budget. The alternative, refusing to track
    anything new, fails open for every account at once.
    """
    for k in [k for k, b in _budgets.items() if not b or now - b[-1] > _SIGN_IN_WINDOW_SECONDS]:
        _budgets.pop(k, None)
    if len(_budgets) < _MAX_TRACKED_KEYS:
        return
    oldest = sorted(_budgets, key=lambda k: _budgets[k][-1] if _budgets[k] else 0.0)
    for k in oldest[: max(1, _MAX_TRACKED_KEYS // 10)]:
        _budgets.pop(k, None)


def _clear(key: str) -> None:
    if config.REDIS_URL:
        from app.infrastructure.cache import _lazy_client, _sync_failed
        client = _lazy_client()
        if client is None:
            return
        try:
            client.delete(f"pai:auth-rate:{key}")
        except Exception as exc:
            _sync_failed(exc)
        return
    _budgets.pop(key, None)


def _source_key(request: Request, scope: str) -> str:
    """Budget key for one caller. Separate scopes so exhausting the signup
    availability check cannot also lock out sign-in."""
    host = request.client.host if request.client else "unknown"
    # Public traffic arrives through Cloudflare Tunnel and private Caddy.
    # A Cloudflare client-IP header is trusted only on that private hop.
    try:
        if ipaddress.ip_address(host).is_private:
            candidate = request.headers.get("cf-connecting-ip", "")
            if candidate:
                host = str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    return f"{scope}:{host}"


class ClaimUsernameRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)


def _session_payload(user, workspace) -> dict:
    return {
        "user": {
            "id": str(user.id), "email": user.email,
            "username": user.username,
            "displayName": user.display_name or user.username or user.email,
        },
        "workspace": {"workspaceId": str(workspace.id), "slug": workspace.slug},
    }


@router.post("/session")
def create_application_session(
    request: Request, db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Exchange a verified Supabase identity for a revocable PAI session."""
    provider_token = extract_bearer(authorization)
    identity = SupabaseIdentityVerifier().verify(provider_token or "")
    if not identity:
        return json_response(ResponseCode.UNAUTHORIZED, "AUTH_INVALID_CREDENTIALS")
    if not identity.email_verified:
        return json_response(ResponseCode.FORBIDDEN, "AUTH_EMAIL_CONFIRMATION_REQUIRED")
    if provider_token_was_revoked(db, provider_token):
        return json_response(ResponseCode.UNAUTHORIZED, "AUTH_SESSION_REVOKED")
    try:
        user = get_or_create_user(db, {
            "provider": identity.provider, "subject": identity.subject,
            "supabase_uid": identity.subject if identity.provider == "supabase" else None,
            "email": identity.email, "username": identity.username,
            "display_name": identity.display_name,
        })
        workspace = get_or_create_owned_workspace(db, user)
        token = create_session(db, user, provider=identity.provider,
                               provider_token=provider_token)
        payload = _session_payload(user, workspace)
        desktop = (request.headers.get("x-pai-desktop") == "1"
                   and request.headers.get("origin", "") in {"", "pai://workspace"})
        if desktop:
            previous = request.headers.get("x-pai-previous-session", "")
            prior = resolve_session(db, previous)
            if prior and str(prior[1].id) == str(user.id):
                revoke_session(db, previous)
            payload["desktopToken"] = token
        db.commit()
    except AuthAccountConflict:
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "AUTH_ACCOUNT_CONFLICT")
    response = JSONResponse(success_response(payload))
    if not desktop:
        response.set_cookie(**cookie_options(), value=token)
    logger.info("auth: PAI session created provider=%s user=%s", identity.provider, user.id)
    return response


@router.get("/session")
def current_application_session(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    user = resolve_current_user(db, authorization)
    if not user:
        return json_response(ResponseCode.UNAUTHORIZED, "AUTH_SESSION_EXPIRED")
    workspace = get_or_create_owned_workspace(db, user)
    token = request.cookies.get(COOKIE_NAME) or extract_bearer(authorization)
    resolved = resolve_session(db, token or "")
    if not resolved:
        return json_response(ResponseCode.UNAUTHORIZED, "AUTH_SESSION_EXPIRED")
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    resolved[0].last_seen_at = now
    resolved[0].expires_at = now + timedelta(seconds=config.PAI_SESSION_TTL_SECONDS)
    payload = _session_payload(user, workspace)
    db.commit()
    response = JSONResponse(success_response(payload))
    if request.cookies.get(COOKIE_NAME):
        response.set_cookie(**cookie_options(), value=token)
    return response


@router.delete("/session")
def end_application_session(
    request: Request, db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    token = request.cookies.get(COOKIE_NAME) or extract_bearer(authorization)
    revoked = revoke_session(db, token or "")
    db.commit()
    response = JSONResponse(success_response({"revoked": revoked}))
    response.delete_cookie(COOKIE_NAME, path="/", samesite="lax")
    if revoked:
        logger.info("auth: PAI session revoked")
    return response


@router.post("/username-available")
def username_available(
    body: ClaimUsernameRequest, request: Request, db: Session = Depends(get_db)
):
    """Validate a username and report whether it can be claimed.

    Unauthenticated by necessity — it runs during signup, before an account
    exists — which makes it an enumeration oracle: "taken" means an account
    holds that name. That is true of every signup form and cannot be designed
    away while usernames are user-chosen. What it should not be is FREE, which
    it was: no limit at all, so the whole namespace could be walked. The source
    budget caps that at a rate no real signup approaches (this is called once
    or twice per signup, not per keystroke).
    """
    source = _source_key(request, "lookup")
    if _over_budget(source, config.AUTH_MAX_REQUESTS_PER_SOURCE_PER_HOUR):
        return json_response(
            ResponseCode.TOO_MANY_REQUESTS, _RATE_LIMITED_MESSAGE, status_code=429
        )
    _charge(source)

    username = _normalize_username(body.username)
    if not username:
        return json_response(
            ResponseCode.BAD_REQUEST,
            f"Username must be {_USERNAME_MIN_LENGTH}-{_USERNAME_MAX_LENGTH} characters: letters, numbers, _ or -",
        )
    existing = db.execute(
        select(User.id).where(func.lower(User.username) == username)
    ).first()
    return success_response({"username": username, "available": existing is None})


@router.post("/claim-username")
def claim_username(
    body: ClaimUsernameRequest,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Attach a unique username to the caller's account.

    Idempotent: re-claiming the same username you already own succeeds
    (called both right after signup and again after email confirmation, once
    a real session exists).
    """
    bearer = extract_bearer(authorization)
    claims = verify_identity_claims(bearer) if bearer else None
    if not claims:
        return json_response(ResponseCode.UNAUTHORIZED, "Invalid or expired token")

    username = _normalize_username(body.username)
    if not username:
        return json_response(
            ResponseCode.BAD_REQUEST,
            f"Username must be {_USERNAME_MIN_LENGTH}-{_USERNAME_MAX_LENGTH} characters: letters, numbers, _ or -",
        )

    user = get_or_create_user(db, claims)
    if user is None:
        return json_response(ResponseCode.UNAUTHORIZED, "Invalid or expired token")

    if user.username == username:
        db.commit()
        return success_response({"username": username})

    existing = db.execute(
        select(User).where(func.lower(User.username) == username, User.id != user.id)
    ).scalar_one_or_none()
    if existing is not None:
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "Username is already taken")

    user.username = username
    try:
        db.commit()
    except IntegrityError:
        # The availability check is advisory. The unique index is the final
        # authority when two signups race for the same normalized username.
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "Username is already taken")
    return success_response({"username": username})


# ---------------------------------------------------------------------------
# Username sign-in — resolves username -> email server-side only. The client
# never learns the email; a wrong username and a wrong password return the
# identical generic error.
# ---------------------------------------------------------------------------

class SignInUsernameRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=4096)


@router.post("/sign-in-username")
def sign_in_username(body: SignInUsernameRequest, request: Request, db: Session = Depends(get_db)):
    source = _source_key(request, "signin")
    username = _normalize_username(body.username)
    account = f"user:{username}" if username else None

    if _over_budget(source, config.AUTH_MAX_REQUESTS_PER_SOURCE_PER_HOUR) or (
        account and _over_budget(account, config.SIGN_IN_USERNAME_MAX_ATTEMPTS_PER_HOUR)
    ):
        return json_response(
            ResponseCode.TOO_MANY_REQUESTS, _RATE_LIMITED_MESSAGE, status_code=429
        )

    def reject():
        """Every rejection costs budget and says the same thing.

        A malformed username, an unknown one and a wrong password are
        indistinguishable in the response. They are NOT indistinguishable in
        timing — only a real account reaches the Supabase round trip below —
        so this is not, by itself, a defence against enumeration. The source
        budget is; and availability is public at /username-available anyway,
        as it is on every signup form.
        """
        _charge(source)
        if account:
            _charge(account)
        return json_response(ResponseCode.UNAUTHORIZED, _GENERIC_SIGN_IN_ERROR)

    if not username:
        return reject()

    user = db.execute(
        select(User).where(func.lower(User.username) == username)
    ).scalar_one_or_none()

    if user is None:
        return reject()

    try:
        import httpx

        resp = httpx.post(
            f"{config.SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": config.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": user.email, "password": body.password},
            timeout=10.0,
        )
    except Exception as e:
        # Our outage, not a bad credential: do not spend the caller's budget.
        logger.warning("auth: sign-in-username Supabase call failed: %s", e)
        return json_response(ResponseCode.INTERNAL_ERROR, "Sign-in is temporarily unavailable")

    if resp.status_code != 200:
        return reject()

    # Correct password: forgive this account's failures so a student who
    # fumbles the password and then gets it right is not locked out next time.
    _clear(account)

    payload = resp.json()
    # Never relay Supabase's user object: it contains the email resolved from
    # the username above. Clients can use the access token with /auth/v1/user.
    return success_response({
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expires_in": payload.get("expires_in"),
        "token_type": payload.get("token_type", "bearer"),
    })
