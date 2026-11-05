"""The hand-off outbox (rule D-a/R-79): a decision version's export is queued in the same DB session as the decision,
so both commit or neither does. Delivery is another task's job."""

from sqlalchemy import select

from app.models import OsOutbox, RouteDecision
from app.pai_c.connect.flags import part_on
from app.pai_c.os_export import decision_record_v2


def record(db, row: RouteDecision, *, consent_only: bool = False) -> OsOutbox | None:
    """Queues the export of `row`. Nothing happens unless CONNECT_HANDOFF and the OS counsellor module are on.
    `consent_only`: `row` is a consent copy of the version before it (only the consent fields differ).
    No commit: the caller's transaction carries it."""
    if not part_on("CONNECT_HANDOFF"):
        return None
    export = decision_record_v2(db, row)
    error = "no_journey" if export is None else None if row.os_supported else "not_supported"
    if error is None and row.status == "chosen" and not (row.places and row.intake):
        error = "incomplete"  # the OS contract needs a programme and an intake for a supported, chosen route
        if consent_only and _same_choice_delivered(db, row):
            error = None  # a consent change on a choice the OS holds is never held back here (C1): the OS must hear
            # of it. The API refuses a supported route without places, so this guards older rows only.
    if error == "not_supported" and row.status == "chosen" and _reached_before(db, row.workspace_id):
        error = None  # a move off a route the OS holds (or is about to): the OS must hear of it to close the old
        # plan (rows 6.3, 6.14). A still-pending version counts too: it will arrive (D-k 2).
    item = OsOutbox(workspace_id=row.workspace_id, kind="decision",
                    key=f"decision:{row.workspace_id}:{row.decision_version}", payload=export,
                    status="pending" if error is None else "not_sent", last_error=error)
    db.add(item)
    db.flush()
    return item


def _reached_before(db, workspace_id: str) -> bool:
    """True when an earlier decision version of the student reached the OS or is still waiting to."""
    return db.scalar(select(OsOutbox.id).where(OsOutbox.workspace_id == workspace_id, OsOutbox.kind == "decision",
                                               OsOutbox.status.in_(("delivered", "pending"))).limit(1)) is not None


def _same_choice_delivered(db, row: RouteDecision) -> bool:
    """True when an earlier version of the same choice (field, destination and level) reached the OS."""
    versions = db.scalars(select(RouteDecision.decision_version).where(
        RouteDecision.workspace_id == row.workspace_id, RouteDecision.decision_version < row.decision_version,
        RouteDecision.status == "chosen", RouteDecision.field_key == row.field_key,
        RouteDecision.destination_country == row.destination_country, RouteDecision.level == row.level)).all()
    keys = [f"decision:{row.workspace_id}:{version}" for version in versions]
    return bool(keys) and db.scalar(select(OsOutbox.id).where(
        OsOutbox.key.in_(keys), OsOutbox.kind == "decision", OsOutbox.status == "delivered").limit(1)) is not None


def pending_for(db, workspace_id: str | None = None) -> list[OsOutbox]:
    """Rows still waiting for delivery, oldest first (one student's, or all)."""
    query = select(OsOutbox).where(OsOutbox.status == "pending")
    if workspace_id is not None:
        query = query.where(OsOutbox.workspace_id == workspace_id)
    return list(db.scalars(query.order_by(OsOutbox.created_at, OsOutbox.key)))
