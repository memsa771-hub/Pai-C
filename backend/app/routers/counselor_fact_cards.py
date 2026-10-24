"""Workspace-authorized catalog card submission."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from app.api.response import success_response
from app.memory.errors import MemoryDataError
from app.database import get_db
from app.routers.roadmaps import _authorized
from app.security.access import is_workspace_owner
from app.pai_c.memory import MemoryService
from app.pai_c.fact_cards import CardAnswer, available_cards, submit_answer

router = APIRouter(prefix="/v1/counselor/fact-cards", tags=["Counselor"])


@router.get("")
def cards(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response({"cards": available_cards(MemoryService(db).profile(str(workspace.id)))})


@router.post("/{key}")
def answer(key: str, body: CardAnswer, network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    # An answer is saved as the student's own statement: only the signed-in
    # student may give it, never an agent holding the machine token.
    if not is_workspace_owner(db, workspace, authorization):
        raise HTTPException(403, "Only the student can change their profile")
    try:
        result = submit_answer(db, str(workspace.id), key, body)
        db.commit()
    except MemoryDataError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    if not result["saved"]:
        raise HTTPException(409, "The profile needs clarification before saving")
    return success_response(result)
