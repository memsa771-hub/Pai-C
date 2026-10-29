"""Remove the Mirror confirm gate (FOUR_FEATURES_SPEC 2.3, 2.4).

Revision ID: 121
Revises: 120

The Mirror is a state card computed from the Vault; nothing is confirmed,
edited or rated any more. The journey follows the Vault, and RESEARCHING,
ASSESSING and NEEDS_INFO are no longer entered. Clean-ups run before the drop,
in this order:
- counselor journeys in MIRROR whose old Mirror was confirmed move to PROPOSED
  when the workspace has a live (not dismissed) path;
- counselor journeys in the old research wait (RESEARCHING, ASSESSING,
  NEEDS_INFO) move to PROPOSED when the workspace has a live path, else MIRROR;
- every stage moved above gets a `journey.stage_changed` event, as the app writes;
- old-shape Mirror drafts (`counselor_summary_draft.type = 'mirror'`) are
  cleared; the new `mirror_state` drafts stay;
- queued jobs of the removed types (`counselor.mirror`,
  `counselor.mirror_research`) are deleted (pending or running only).
Then `pai_counselor_mirror_feedback` (the "understood" rating) is dropped.

Downgrade recreates the feedback table empty (the 110 shape). It leaves stages
and drafts as they are.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "121"
down_revision = "120"
branch_labels = depends_on = None

_COUNSELOR = "journey_type = 'counselor_decision'"
_WAITING = "current_stage IN ('RESEARCHING', 'ASSESSING', 'NEEDS_INFO')"
_OLD_CONFIRMED = ("counselor_summary_draft->>'type' = 'mirror' "
                  "AND counselor_summary_draft->>'status' = 'confirmed'")
_LIVE_PATH = ("EXISTS (SELECT 1 FROM pai_possibilities p WHERE p.workspace_id = pai_student_journeys.workspace_id "
              "AND p.status <> 'dismissed')")


def _move(where: str, to: str) -> tuple[str, str]:
    """A stage move as the app makes it: the stage_changed event (written
    first, while the old stage is still there to read), then the update."""
    event = ("INSERT INTO pai_student_journey_events (id, journey_id, workspace_id, event_type, payload, actor, "
             "created_at) SELECT CAST(gen_random_uuid() AS TEXT), id, workspace_id, 'journey.stage_changed', "
             f"jsonb_build_object('from', current_stage, 'to', {to}), 'system:migration_121', NOW() "
             f"FROM pai_student_journeys WHERE {where}")
    update = f"UPDATE pai_student_journeys SET current_stage = {to}, updated_at = NOW() WHERE {where}"
    return event, update


# MIRROR first: the waiting journeys it does not see may land in MIRROR below.
MOVE_CONFIRMED_MIRROR = _move(f"{_COUNSELOR} AND current_stage = 'MIRROR' AND {_OLD_CONFIRMED} AND {_LIVE_PATH}",
                              "'PROPOSED'")
MOVE_WAITING = _move(f"{_COUNSELOR} AND {_WAITING}", f"CASE WHEN {_LIVE_PATH} THEN 'PROPOSED' ELSE 'MIRROR' END")
# Last: the moves above read the old draft.
CLEAR_OLD_DRAFTS = ("UPDATE pai_student_journeys SET counselor_summary_draft = NULL "
                    "WHERE counselor_summary_draft->>'type' = 'mirror'")
DELETE_DEAD_JOBS = ("DELETE FROM background_jobs WHERE job_type IN ('counselor.mirror', 'counselor.mirror_research') "
                    "AND status IN ('pending', 'running')")
CLEANUP = (*MOVE_CONFIRMED_MIRROR, *MOVE_WAITING, CLEAR_OLD_DRAFTS, DELETE_DEAD_JOBS)


def upgrade():
    for statement in CLEANUP:
        op.execute(statement)
    op.drop_table("pai_counselor_mirror_feedback")


def downgrade():
    op.create_table("pai_counselor_mirror_feedback",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mirror_version", sa.Integer(), nullable=False),
        sa.Column("understood", sa.Integer(), nullable=False),
        sa.Column("certainty_after", sa.Integer(), nullable=True),
        sa.Column("certainty_before", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("workspace_id", "mirror_version", name="uq_mirror_feedback_version"),
        sa.CheckConstraint("mirror_version >= 1", name="ck_mirror_feedback_version"),
        sa.CheckConstraint("understood BETWEEN 1 AND 5", name="ck_mirror_feedback_understood"),
        sa.CheckConstraint("certainty_after BETWEEN 0 AND 10", name="ck_mirror_feedback_after"),
        sa.CheckConstraint("certainty_before BETWEEN 0 AND 10", name="ck_mirror_feedback_before"))
