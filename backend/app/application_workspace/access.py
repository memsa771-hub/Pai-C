"""Workspace and student identity boundary shared by application endpoints."""
from app.api.response import ResponseCode, json_response
from app.routers.network import _resolve_workspace, _verify_workspace_access
from app.security.event_identity import resolve_human


def _auth(db, network, token, authorization, *, write=False):
    workspace = _resolve_workspace(db, network)
    if workspace is None:
        return None, json_response(ResponseCode.NOT_FOUND, "Workspace not found")
    if not _verify_workspace_access(workspace, token, authorization):
        return None, json_response(ResponseCode.UNAUTHORIZED, "Invalid credentials")
    if write and resolve_human(db, workspace, authorization) is None:
        return None, json_response(ResponseCode.FORBIDDEN, "Student account required")
    return workspace, None
