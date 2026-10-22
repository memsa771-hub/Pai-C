"""The "a few more details" form (Slice 6a spec S6a-D4): the data-sheet fields no document shows. The student types
them, so they are confirmed profile values with the source "entered" and no document (invariant 4)."""

from sqlalchemy import Engine

from app.os.documents.store import ProfileStore
from app.os.packs.config import ENTERED, PackConfig
from app.os.packs.inputs import ENTERED_PREFIX


def save_details(engine: Engine, tenant_id: str, cfg: PackConfig, student_ref: str, fields: dict) -> None:
    """Only the route's `entered` fields; any other key is refused (`ValueError`, naming it). An empty value clears it."""
    allowed = {f.key for f in cfg.fields() if f.source == ENTERED}
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise ValueError(f"these are not details you can type here: {', '.join(unknown)}")
    profile = ProfileStore(engine, tenant_id)
    for key, value in fields.items():
        text = None if value is None else str(value).strip()
        profile.set(student_ref, ENTERED_PREFIX + key, text or None, None, source="entered")
