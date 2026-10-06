"""Institution search and student-owned saved college list."""
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.models import Institution, SavedInstitution
from .access import _auth
from .queries import _visible_institution
from .schemas import InstitutionInput, NetworkInput
from .serializers import _institution

router = APIRouter()

@router.get("/institutions")
def search_institutions(network: str = Query(...), q: str = Query("", max_length=160),
                        country_code: str | None = Query(None), limit: int = Query(30, ge=1, le=100),
                        db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                        authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    query = select(Institution).where(or_(Institution.owner_workspace_id.is_(None), Institution.owner_workspace_id == workspace_id))
    if q.strip():
        # Literal search: user input never becomes a LIKE wildcard.
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Institution.name.ilike(f"%{term}%", escape="\\"))
    if country_code:
        query = query.where(Institution.country_code == country_code.strip().upper())
    rows = db.execute(query.order_by(Institution.name, Institution.id).limit(limit)).scalars().all()
    saved = set(db.execute(select(SavedInstitution.institution_id).where(SavedInstitution.workspace_id == workspace_id)).scalars())
    return success_response([_institution(row, row.id in saved) for row in rows])


@router.post("/institutions")
def add_institution(body: InstitutionInput, db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    workspace_id = str(workspace.id)
    name = body.name.strip()
    country = body.country_code.upper()
    normalized = name.casefold()
    # Prefer a trusted catalog identity when it already exists.
    row = db.execute(select(Institution).where(Institution.owner_workspace_id.is_(None),
                                               Institution.country_code == country,
                                               Institution.normalized_name == normalized)).scalar_one_or_none()
    if row is None:
        row = db.execute(select(Institution).where(Institution.owner_workspace_id == workspace_id,
                                                   Institution.country_code == country,
                                                   Institution.normalized_name == normalized)).scalar_one_or_none()
    if row is None:
        row = Institution(owner_workspace_id=workspace_id, name=name, normalized_name=normalized,
                          country_code=country, city=body.city, website_url=str(body.website_url) if body.website_url else None)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return json_response(ResponseCode.CONFLICT, "Institution already exists; search and save it")
    saved = db.execute(select(SavedInstitution).where(SavedInstitution.workspace_id == workspace_id,
                                                      SavedInstitution.institution_id == row.id)).scalar_one_or_none()
    if saved is None:
        db.add(SavedInstitution(workspace_id=workspace_id, institution_id=row.id))
    db.commit()
    return success_response(_institution(row, True))


@router.get("/saved")
def list_saved(network: str = Query(...), db: Session = Depends(get_db),
               x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization)
    if error:
        return error
    rows = db.execute(select(Institution).join(SavedInstitution, SavedInstitution.institution_id == Institution.id)
                      .where(SavedInstitution.workspace_id == str(workspace.id)).order_by(Institution.name)).scalars().all()
    return success_response([_institution(row, True) for row in rows])


@router.post("/saved/{institution_id}")
def save_institution(institution_id: str, body: NetworkInput, db: Session = Depends(get_db),
                     x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    workspace_id = str(workspace.id)
    row = _visible_institution(db, workspace_id, institution_id)
    if row is None:
        return json_response(ResponseCode.NOT_FOUND, "Institution not found")
    existing = db.execute(select(SavedInstitution).where(SavedInstitution.workspace_id == workspace_id,
                                                         SavedInstitution.institution_id == row.id)).scalar_one_or_none()
    if existing is None:
        db.add(SavedInstitution(workspace_id=workspace_id, institution_id=row.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # idempotent under concurrent saves
    return success_response(_institution(row, True))


@router.delete("/saved/{institution_id}")
def unsave_institution(institution_id: str, network: str = Query(...), db: Session = Depends(get_db),
                       x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization, write=True)
    if error:
        return error
    row = db.execute(select(SavedInstitution).where(SavedInstitution.workspace_id == str(workspace.id),
                                                    SavedInstitution.institution_id == institution_id)).scalar_one_or_none()
    if row:
        db.delete(row)
        db.commit()
    return success_response({"saved": False})


