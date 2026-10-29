"""Journey stage sync: the Mirror edge and the re-plan guard (FOUR_FEATURES_SPEC 2.4).

Revision ID: 122
Revises: 121

Two nullable timestamps on the counselor journey:
- `mirror_ready_at`: when the journey first passed the Mirror (DIRECTION ->
  MIRROR). DIRECTION -> MIRROR is automatic only on that first edge;
- `replan_at`: set when a rethink or a PAI OS escalation moves the journey
  back to DIRECTION. While it is set no automatic stage move happens; the
  student's own act (choosing a route, or asking for paths and getting them)
  ends it.

Journeys already in DIRECTION whose last stage change came from PROPOSED or
CHOSEN were re-planning before this column existed; they get `replan_at` now.

Also drops `uq_counselor_mirror_pending` (migration 098): the
`counselor.mirror` job type it guarded is gone (121). Downgrade recreates it
and drops the two columns.
"""
from alembic import op
import sqlalchemy as sa

revision = "122"
down_revision = "121"
branch_labels = depends_on = None

TABLE = "pai_student_journeys"
BACKFILL_REPLAN = (
    "UPDATE pai_student_journeys SET replan_at = NOW() "
    "WHERE journey_type = 'counselor_decision' AND current_stage = 'DIRECTION' AND ("
    "SELECT e.payload->>'from' FROM pai_student_journey_events e "
    "WHERE e.journey_id = pai_student_journeys.id AND e.event_type = 'journey.stage_changed' "
    "ORDER BY e.created_at DESC LIMIT 1) IN ('PROPOSED', 'CHOSEN')")


def upgrade():
    op.add_column(TABLE, sa.Column("mirror_ready_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("replan_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(BACKFILL_REPLAN)
    op.drop_index("uq_counselor_mirror_pending", table_name="background_jobs")


def downgrade():
    op.create_index("uq_counselor_mirror_pending", "background_jobs", ["workspace_id"], unique=True,
        postgresql_where=sa.text("job_type = 'counselor.mirror' AND status IN ('pending', 'running')"))
    op.drop_column(TABLE, "replan_at")
    op.drop_column(TABLE, "mirror_ready_at")
