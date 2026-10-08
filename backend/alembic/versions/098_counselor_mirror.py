"""Mirror stage and at most one pending/running Mirror per workspace.

Revision ID: 098
Revises: 097
"""

from alembic import op
import sqlalchemy as sa

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None

_STAGES = ("ORIENTING", "UNDERSTANDING", "ALIGNING", "PLANNING", "ACTING", "REVIEWING",
           "COMPLETED", "IDENTITY", "FOUNDATION", "DIRECTION", "RESEARCHING", "ASSESSING",
           "NEEDS_INFO", "PROPOSED", "CHOSEN")


def _constraint(stages):
    op.drop_constraint("ck_student_journey_stage", "pai_student_journeys", type_="check")
    op.create_check_constraint("ck_student_journey_stage", "pai_student_journeys",
        "current_stage IS NULL OR current_stage IN (" + ",".join(repr(stage) for stage in stages) + ")")


def upgrade():
    _constraint((*_STAGES, "MIRROR"))
    op.create_index("uq_counselor_mirror_pending", "background_jobs", ["workspace_id"], unique=True,
        postgresql_where=sa.text("job_type = 'counselor.mirror' AND status IN ('pending', 'running')"))


def downgrade():
    op.drop_index("uq_counselor_mirror_pending", table_name="background_jobs")
    op.execute("UPDATE pai_student_journeys SET current_stage = 'DIRECTION' WHERE current_stage = 'MIRROR'")
    _constraint(_STAGES)
