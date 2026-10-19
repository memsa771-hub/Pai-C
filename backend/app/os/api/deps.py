"""Ports for the API: who the student is (provided by the host app) and the admin token check."""

import hmac

from fastapi import HTTPException

from app.os.settings import OsSettings


def current_student_ref() -> str:
    """Overridden by the host app (app/main.py) with its signed-in student. The OS never imports host auth."""
    raise HTTPException(status_code=401, detail="student sign-in required")


def check_admin(settings: OsSettings, authorization: str | None) -> None:
    token = settings.admin_token
    given = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    if not token or not given or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="admin token required")
