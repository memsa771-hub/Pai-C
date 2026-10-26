"""The Roadmap page API: the engine's fields for the student and their chosen
route (spec ROADMAP_ENGINE_SPEC.md §3). Reads compute on request; writes only
touch pai_route_decisions."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.api.response import success_response
from app.database import get_db
from app.pai_c.roadmap.decisions import RouteDecisionError, RouteDecisionService
from app.pai_c.roadmap.engine import RoadmapEngine
from app.routers._workspace_auth import _authorized

router = APIRouter(prefix="/v1/roadmap", tags=["Roadmap"])


class ChooseAction(BaseModel):
    field_key: str = Field(min_length=1, max_length=120)


class StepAction(BaseModel):
    index: int = Field(ge=0)
    done: bool


def _write(action, db):
    try:
        result = action()
    except RouteDecisionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except IntegrityError as exc:  # a concurrent choice won the one-active-route index
        db.rollback()
        raise HTTPException(status_code=409, detail="Another route was just chosen; reload the page") from exc
    db.commit()
    return success_response(result)


@router.get("")
def get_roadmap(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None),
                authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response(RoadmapEngine(db).build(str(workspace.id)))


@router.post("/choose")
def choose_route(body: ChooseAction, network: str = Query(...), db=Depends(get_db),
                 x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _write(lambda: RouteDecisionService(db).choose(str(workspace.id), body.field_key), db)


@router.post("/steps")
def tick_step(body: StepAction, network: str = Query(...), db=Depends(get_db),
              x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _write(lambda: RouteDecisionService(db).set_step(str(workspace.id), body.index, body.done), db)


@router.post("/withdraw")
def withdraw_route(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None),
                   authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _write(lambda: RouteDecisionService(db).withdraw(str(workspace.id)), db)
