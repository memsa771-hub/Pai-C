# -*- coding: utf-8 -*-
"""
Auth endpoints for provider identity exchange and PAI sessions.

There are no usernames: students sign in with email and password or Google.

Supabase verifies credentials. PAI resolves a stable account and owns the
revocable application session used by protected workspace APIs.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import config
from app.database import get_db
from app.security.identity import SupabaseIdentityVerifier
from app.security.access import (
    AuthAccountConflict, extract_bearer, get_or_create_owned_workspace,
    get_or_create_user, resolve_current_user,
)
from app.security.app_session import (
    COOKIE_NAME, cookie_options, create_session, provider_token_was_revoked,
    resolve_session, revoke_session,
)
from app.api.response import ResponseCode, json_response, success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

def _session_payload(user, workspace) -> dict:
    return {
        "user": {
            "id": str(user.id), "email": user.email,
            "displayName": user.display_name or user.email,
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
            "email": identity.email, "display_name": identity.display_name,
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
