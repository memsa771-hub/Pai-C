"""Read-only living picture for the owner's Counselor workspace."""
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from app.database import get_db
from app.api.response import success_response
from app.routers.roadmaps import _authorized
from app.models import CounselorMirrorFeedback, StudentJourney, CounselorTurnDecision
from app.pai_c.memory import MemoryService

router=APIRouter(prefix='/v1/counselor',tags=['Counselor'])


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
    return success_response({'coverage':memory.coverage_areas(wid),'personal':personal,
        'capabilities':memory.capability_view(wid),'academic':memory.academic_view(wid),
        'picture':(draft.get('mirror') or {}).get('core_picture') if draft.get('status')=='confirmed' else None,
        'mirror_status':draft.get('status'),'moments':moments,
        'ratings':[{'version':r.mirror_version,'understood':r.understood,'before':r.certainty_before,
                    'after':r.certainty_after} for r in feedback]})
