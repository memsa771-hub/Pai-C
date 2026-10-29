"""The Mirror state card. There is no confirm, edit or rating route: the card
follows the Vault, and corrections are Vault writes (FOUR_FEATURES_SPEC 2.3)."""

from fastapi import APIRouter, Depends, Header, Query

from app.api.response import success_response
from app.database import get_db
from app.routers._workspace_auth import _authorized

router = APIRouter(prefix="/v1/counselor", tags=["Counselor"])


@router.get("/summary")
def current_summary(network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None),
                    authorization: str | None = Header(None)):
    """The Mirror state card, computed from the Vault on this read."""
    from app.pai_c.mirror import MirrorEngine
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response({"type": "mirror_state", "card": MirrorEngine(db).build(str(workspace.id))})
