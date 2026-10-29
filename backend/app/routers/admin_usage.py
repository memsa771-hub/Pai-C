"""GET /v1/admin/usage: this month's estimated model spend, for the founder.

There is no admin role in the product, so the reader is a signed-in account
whose email is listed in PAI_FOUNDER_EMAILS (Firebase bearer, as /v1/account).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.config import config
from app.database import get_db
from app.inference import usage
from app.security.access import resolve_current_user

router = APIRouter(prefix="/v1/admin", tags=["Admin"])


def _founders() -> set[str]:
    return {email.strip().lower() for email in config.PAI_FOUNDER_EMAILS.split(",") if email.strip()}


@router.get("/usage")
def admin_usage(db: Session = Depends(get_db), authorization: Optional[str] = Header(None)):
    user = resolve_current_user(db, authorization)
    if not user:
        return json_response(ResponseCode.UNAUTHORIZED, "Invalid identity token")
    if (user.email or "").strip().lower() not in _founders():
        return json_response(ResponseCode.FORBIDDEN, "Founder access only")
    state = usage.cap_state()
    by_role = []
    for scope, calls, est_usd in usage.month_rows(state["month"]):
        role = scope.split(":", 1)[1] if scope.startswith(usage.MODELS_SCOPE + ":") else scope
        by_role.append({"role": role, "calls": calls, "est_usd": round(est_usd, 6)})
    by_role.sort(key=lambda row: row["est_usd"], reverse=True)
    return success_response({"month": state["month"], "cap": state["cap"], "spent": state["spent"],
                             "stage": state["stage"], "by_role": by_role})
