# -*- coding: utf-8 -*-
"""Account endpoints around Firebase Auth, shared by web, desktop and mobile.

Firebase verifies credentials; every protected API checks the Firebase ID
token itself (app.security.human_auth). These endpoints cover what Firebase
must not do on its own: our emails go through Resend, links open our own
/auth/action page, and a sign-in from a new device sends an alert.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.config import config
from app.database import get_db
from app.models import AuthDevice
from app.security.access import (
    AuthAccountConflict, extract_bearer, get_or_create_owned_workspace, get_or_create_user,
)
from app.security.errors import EmailNotVerified
from app.security import firebase_auth
from app.security import rate_limit
from app.services import auth_emails

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited():
    return json_response(ResponseCode.TOO_MANY_REQUESTS, "AUTH_RATE_LIMITED", status_code=429)


class SessionRequest(BaseModel):
    # A random id the client keeps per browser/app install; only its hash is stored.
    deviceId: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    oobCode: str = Field(min_length=1, max_length=2048)
    newPassword: str = Field(min_length=1, max_length=4096)


def _device_label(user_agent: str) -> str:
    agent = user_agent.lower()
    browser = next((name for key, name in (("edg/", "Edge"), ("chrome/", "Chrome"), ("firefox/", "Firefox"),
                                           ("safari/", "Safari")) if key in agent), "a browser")
    system = next((name for key, name in (("android", "Android"), ("iphone", "iPhone"), ("ipad", "iPad"),
                                          ("windows", "Windows"), ("mac os", "Mac"), ("linux", "Linux"))
                   if key in agent), "an unknown system")
    return f"{browser} on {system}"


@router.post("/session")
def start_session(
    body: SessionRequest, request: Request, background: BackgroundTasks,
    db: Session = Depends(get_db), authorization: Optional[str] = Header(None),
):
    """Called after every sign-in: links the account, notes the device, alerts on a new one."""
    identity = firebase_auth.verify_token(extract_bearer(authorization) or "")
    if identity is None:
        return json_response(ResponseCode.UNAUTHORIZED, "AUTH_INVALID_CREDENTIALS")
    if not rate_limit.allow("session", user=identity.subject):
        return _rate_limited()
    if identity.needs_email_verification:
        raise EmailNotVerified()
    try:
        user = get_or_create_user(db, {
            "provider": identity.provider, "subject": identity.subject,
            "email": identity.email, "display_name": identity.display_name,
        })
        workspace = get_or_create_owned_workspace(db, user)
    except AuthAccountConflict:
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "AUTH_ACCOUNT_CONFLICT")

    device_hash = hashlib.sha256(f"pai-device-v1:{body.deviceId}".encode()).hexdigest()
    user_agent = (request.headers.get("user-agent") or "")[:300]
    now = datetime.now(timezone.utc)
    device = db.execute(select(AuthDevice).where(
        AuthDevice.user_id == user.id, AuthDevice.device_hash == device_hash)).scalar_one_or_none()
    new_device = device is None
    known = 0
    if device is None:
        # The first device an account ever uses (right after sign-up) is not "new".
        known = db.execute(select(func.count()).select_from(AuthDevice)
                           .where(AuthDevice.user_id == user.id)).scalar_one()
        db.add(AuthDevice(user_id=user.id, device_hash=device_hash, user_agent=user_agent))
    else:
        device.last_seen_at = now
        device.user_agent = user_agent or device.user_agent
    try:
        db.commit()
    except IntegrityError:
        # A parallel sign-in from this device recorded it first; that one sends the alert.
        db.rollback()
        new_device = False
    if new_device and known:
        background.add_task(auth_emails.send_new_sign_in_email, user.email,
                            _device_label(user_agent), now.strftime("%d %b %Y, %H:%M UTC"))
    logger.info("auth: session user=%s new_device=%s", user.id, new_device)
    return success_response({
        "user": {"id": str(user.id), "email": user.email, "displayName": user.display_name or user.email},
        "workspace": {"workspaceId": str(workspace.id), "slug": workspace.slug},
        "newDevice": new_device,
    })


@router.post("/send-verification")
def send_verification(
    request: Request, background: BackgroundTasks, authorization: Optional[str] = Header(None),
):
    """Email a verification link to the signed-in (not yet verified) account."""
    identity = firebase_auth.verify_token(extract_bearer(authorization) or "")
    if identity is None:
        return json_response(ResponseCode.UNAUTHORIZED, "AUTH_INVALID_CREDENTIALS")
    if identity.email_verified:
        return success_response({"sent": False, "alreadyVerified": True})
    if not rate_limit.allow("send_verification", user=identity.subject):
        return _rate_limited()
    code = firebase_auth.email_verification_code(identity.email)
    background.add_task(auth_emails.send_verification_email, identity.email, code)
    return success_response({"sent": True, "alreadyVerified": False})


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, request: Request, background: BackgroundTasks):
    """Email a reset link. The answer is the same whether or not the account exists."""
    email = body.email.strip().lower()
    if not rate_limit.allow("forgot_password", email=email, ip=_client_ip(request)):
        return _rate_limited()
    if "@" in email:
        code = firebase_auth.password_reset_code(email)
        if code:
            background.add_task(auth_emails.send_password_reset_email, email, code)
    return success_response({"sent": True})


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, request: Request):
    """Set the new password from a reset link, then sign the account out everywhere."""
    if not rate_limit.allow("reset_password", ip=_client_ip(request)):
        return _rate_limited()
    try:
        firebase_auth.reset_password(body.oobCode, body.newPassword)
    except firebase_auth.ResetLinkInvalid:
        return json_response(ResponseCode.BAD_REQUEST, "AUTH_RESET_LINK_INVALID", status_code=400)
    except firebase_auth.WeakPassword:
        return json_response(ResponseCode.BAD_REQUEST, "AUTH_WEAK_PASSWORD", status_code=400)
    logger.info("auth: password reset, every session revoked")
    return success_response({"reset": True})
