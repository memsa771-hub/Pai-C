# -*- coding: utf-8 -*-
"""
The guardian's one-time link (R-10): public, no sign-in. The token in the path is the only credential.

GET  /v1/guardian/{token}            What the page shows for the token's own kind (agree or withdraw) (no change except the audit row)
POST /v1/guardian/{token}/agree      The guardian agrees
GET  /v1/guardian/{token}/withdraw   What the withdraw page shows (no change except the audit row)
POST /v1/guardian/{token}/withdraw   The guardian withdraws

A mail scanner may open any link, so GET never agrees or withdraws. Answers carry the first name of the student and
nothing else about them, never an e-mail address, never the token hash. `Cache-Control: no-store` and
`Referrer-Policy: no-referrer` are set for every /v1/guardian/ answer by the middleware in app/main.py, which also
logs the route template instead of the path, so the token stays out of the logs.
"""

import logging

from fastapi import APIRouter, Depends, Request

from app import pai_os_bridge

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.pai_c.connect import flags, guardian
from app.pai_c.connect.consent import ConsentTextNotApproved

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/guardian", tags=["Guardian"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _answer(db, call, idle=None):
    if not flags.part_on("CONNECT_HANDOFF"):  # the connection is off: nothing is read or written
        return success_response({"state": "stale", "text": None, "student_first_name": None} if idle is None else idle)
    try:
        result = call()
    except guardian.GuardianRateLimited:
        db.rollback()
        return json_response(ResponseCode.TOO_MANY_REQUESTS, "TOO_MANY_REQUESTS", status_code=429)
    except ConsentTextNotApproved:
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "CONSENT_TEXT_NOT_APPROVED", status_code=409)
    db.commit()
    return success_response(result)


@router.get("/{token}")
def open_agree_page(token: str, request: Request, db=Depends(get_db)):
    return _answer(db, lambda: guardian.open(db, token, ip=_ip(request)))


def _changed(db, token: str, state: str, done: str) -> None:
    """A consent change is saved: hand the new version to PAI OS now (the 5-minute sweep would do it anyway)."""
    if state != done:
        return
    try:
        pai_os_bridge.deliver_pending(db, guardian.workspace_of(db, token))
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("PAI OS delivery after a guardian answer failed")


@router.post("/{token}/agree")
def agree(token: str, request: Request, db=Depends(get_db)):
    def call():
        state, sent = guardian.agree_with_mail(db, token, ip=_ip(request))
        return {"state": state, **({"confirmation_sent": sent} if state == "agreed" else {})}

    answer = _answer(db, call, {"state": "stale"})
    if isinstance(answer, dict):
        _changed(db, token, answer["data"]["state"], "agreed")
    return answer


@router.get("/{token}/withdraw")
def open_withdraw_page(token: str, request: Request, db=Depends(get_db)):
    return _answer(db, lambda: guardian.open(db, token, ip=_ip(request), purpose=guardian.WITHDRAW))


@router.post("/{token}/withdraw")
def withdraw(token: str, request: Request, db=Depends(get_db)):
    answer = _answer(db, lambda: {"state": guardian.withdraw(db, token, ip=_ip(request))},
                    {"state": "stale"})
    if isinstance(answer, dict):
        _changed(db, token, answer["data"]["state"], "withdrawn")
    return answer
