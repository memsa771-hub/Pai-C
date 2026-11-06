# -*- coding: utf-8 -*-
"""
The one upload entry point, Counsellor side (P1-T7, R-01, row 6.7). Both routes answer only while the part is on
(CONNECT_ONE_UPLOAD and the OS `counsellor` module); with it off, `options` says so and nothing else changes.

GET  /v1/uploads/options                    What the upload screens need (types and sentences), or one_upload=false
POST /v1/uploads/{file_id}/os-document      Make a stored file an OS document of the type the student names
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.files.storage import get_file_store
from app.models import FileRecord
from app.pai_c.connect.flags import part_on
from app.routers.network import _resolve_workspace, _verify_workspace_access
from app.security.event_identity import resolve_human

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Uploads"])


class OsDocumentRequest(BaseModel):
    doc_type: str


@router.get("/uploads/options")
def upload_options(
    network: str = Query(..., description="Network (workspace) ID or slug"),
    x_workspace_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Whether the one upload entry point is on, and if so the document types and the sentences to show."""
    workspace = _resolve_workspace(db, network)
    if not workspace:
        return json_response(ResponseCode.NOT_FOUND, "Network not found")
    if not _verify_workspace_access(workspace, x_workspace_token, authorization):
        return json_response(ResponseCode.UNAUTHORIZED, "Invalid workspace credentials")
    from app.pai_c.connect import uploads

    return success_response(uploads.options())


@router.post("/uploads/{file_id}/os-document")
def register_os_document(
    file_id: str,
    body: OsDocumentRequest,
    network: str = Query(..., description="Network (workspace) ID or slug"),
    x_workspace_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Makes a file the student already stored (for example a chat attachment) an OS document of the type they pick.
    The signed-in student only. 409 while the part is off. 404 for a file that is not an active file of the workspace."""
    workspace = _resolve_workspace(db, network)
    if not workspace:
        return json_response(ResponseCode.NOT_FOUND, "Network not found")
    if not _verify_workspace_access(workspace, x_workspace_token, authorization):
        return json_response(ResponseCode.UNAUTHORIZED, "Invalid workspace credentials")
    if resolve_human(db, workspace, authorization) is None:
        return json_response(ResponseCode.FORBIDDEN, "Student account required")
    if not part_on("CONNECT_ONE_UPLOAD"):
        return json_response(ResponseCode.CONFLICT, "Uploading to the OS from here is not on")
    record = db.execute(
        select(FileRecord)
        .where(FileRecord.id == file_id)
        .where(FileRecord.workspace_id == str(workspace.id))
        .where(FileRecord.status == "active")
    ).scalar_one_or_none()
    if record is None:
        return json_response(ResponseCode.NOT_FOUND, "File not found")
    try:
        data = get_file_store().read(record.storage_key)
    except Exception as exc:  # noqa: BLE001  (class name only)
        logger.error("stored file could not be read for the OS: %s", type(exc).__name__)
        return json_response(ResponseCode.NOT_FOUND, "File not found")
    from app.pai_c.connect import uploads

    result = uploads.register_typed(db, str(workspace.id), record.id, data, record.filename, body.doc_type)
    return success_response({"os_document": result})
