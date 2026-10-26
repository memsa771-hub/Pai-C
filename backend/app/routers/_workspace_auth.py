"""Workspace auth shared by the student-facing routers.

Lives in its own module so routers do not import each other for it (it used to
sit in routers/roadmaps.py, which the roadmap engine replaces).
"""

from fastapi import HTTPException

from app.routers.network import _resolve_workspace, _verify_workspace_access


def _authorized(db, network, token, authorization):
    workspace = _resolve_workspace(db, network)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not _verify_workspace_access(workspace, token, authorization):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return workspace
