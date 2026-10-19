"""Read-only living picture for the owner's Counselor workspace."""
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from app.database import get_db
from app.api.response import success_response
from app.routers.roadmaps import _authorized
from app.models import CounselorMirrorFeedback, StudentJourney, CounselorTurnDecision
from app.pai_c.memory import MemoryService
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from fastapi import HTTPException

router=APIRouter(prefix='/v1/counselor',tags=['Counselor'])


class FamilyPreparation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    submission_id: UUID
    path_id: str = Field(min_length=1)
    person_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


@router.get('/family-talk')
def family_talk(network: str=Query(...), db=Depends(get_db),
    x_workspace_token: str | None=Header(None), authorization: str | None=Header(None)):
    from app.pai_c.family_talk import prepare
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response(prepare(db, str(workspace.id)))


@router.post('/family-talk')
async def send_family_talk(body: FamilyPreparation, network: str=Query(...), db=Depends(get_db),
    x_workspace_token: str | None=Header(None), authorization: str | None=Header(None)):
    from app.pai_c.family_talk import deliver
    workspace = _authorized(db, network, x_workspace_token, authorization)
    try:
        return success_response(await deliver(db, str(workspace.id), body))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/workspace')
def counselor_workspace(network: str=Query(...),db=Depends(get_db),
    x_workspace_token: str | None=Header(None),authorization: str | None=Header(None)):
    workspace=_authorized(db,network,x_workspace_token,authorization)
    wid=str(workspace.id)
    memory=MemoryService(db)
    journey=db.scalar(select(StudentJourney).where(StudentJourney.workspace_id==wid,
        StudentJourney.journey_type=='counselor_decision',StudentJourney.status=='active'))
    draft=(journey.counselor_summary_draft or {}) if journey else {}
    personal=memory.personal_view(wid)
    feedback=db.scalars(select(CounselorMirrorFeedback).where(CounselorMirrorFeedback.workspace_id==wid)
        .order_by(CounselorMirrorFeedback.created_at)).all()
    turns=db.scalars(select(CounselorTurnDecision).where(CounselorTurnDecision.workspace_id==wid)
        .order_by(CounselorTurnDecision.source_timestamp)).all()
    moments={}
    for turn in turns:
        action=(turn.decision or {}).get('action')
        if action and action not in moments: moments[action]=turn.source_event_id
    return success_response({'coverage':memory.coverage_areas(wid),'personal':personal, 'sections':memory.profile_sections(wid),
        'capabilities':memory.capability_view(wid),'academic':memory.academic_view(wid),
        'picture':(draft.get('mirror') or {}).get('core_picture') if draft.get('status')=='confirmed' else None,
        'mirror_status':draft.get('status'),'moments':moments,
        'ratings':[{'version':r.mirror_version,'understood':r.understood,'before':r.certainty_before,
                    'after':r.certainty_after} for r in feedback]})


@router.get('/export')
def export_data(network: str=Query(...), db=Depends(get_db),
    x_workspace_token: str | None=Header(None), authorization: str | None=Header(None)):
    from app.pai_c.data_export import export_student_data
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response(export_student_data(db, str(workspace.id)))
