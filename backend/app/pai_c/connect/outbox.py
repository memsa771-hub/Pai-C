"""The hand-off outbox (rule D-a/R-79): a decision version's export is queued in the same DB session as the decision,
so both commit or neither does. Delivery is another task's job."""

from sqlalchemy import select

from app.models import OsOutbox, RouteDecision
from app.pai_c.connect.flags import part_on
from app.pai_c.os_export import decision_record_v2


def record(db, row: RouteDecision) -> OsOutbox | None:
    """Queues the export of `row`. Nothing happens unless CONNECT_HANDOFF and the OS counsellor module are on.
    No commit: the caller's transaction carries it."""
    if not part_on("CONNECT_HANDOFF"):
        return None
    export = decision_record_v2(db, row)
    error = "no_journey" if export is None else None if row.os_supported else "not_supported"
    if error is None and row.status == "chosen" and not (row.places and row.intake):
        error = "incomplete"  # the OS contract needs a programme and an intake for a supported, chosen route
    if error == "not_supported" and row.status == "chosen" and _delivered_before(db, row.workspace_id):
        error = None  # a move off a route the OS holds: the OS must hear of it to close the old plan (rows 6.3, 6.14)
    item = OsOutbox(workspace_id=row.workspace_id, kind="decision",
                    key=f"decision:{row.workspace_id}:{row.decision_version}", payload=export,
                    status="pending" if error is None else "not_sent", last_error=error)
    db.add(item)
    db.flush()
    return item


def _delivered_before(db, workspace_id: str) -> bool:
    """True when an earlier decision version of the student reached the OS."""
    return db.scalar(select(OsOutbox.id).where(OsOutbox.workspace_id == workspace_id, OsOutbox.kind == "decision",
                                               OsOutbox.status == "delivered").limit(1)) is not None


def pending_for(db, workspace_id: str | None = None) -> list[OsOutbox]:
    """Rows still waiting for delivery, oldest first (one student's, or all)."""
    query = select(OsOutbox).where(OsOutbox.status == "pending")
    if workspace_id is not None:
        query = query.where(OsOutbox.workspace_id == workspace_id)
    return list(db.scalars(query.order_by(OsOutbox.created_at, OsOutbox.key)))
