"""Link roadmap details to the exact versioned evidence used to build them.

Revision ID: 094
Revises: 093
"""

from alembic import op
import sqlalchemy as sa

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pai_roadmaps", sa.Column("requirement_set_id", sa.Text(),
                                          sa.ForeignKey("pai_requirement_sets.id", ondelete="SET NULL")))
    op.create_index("idx_roadmaps_requirement_set", "pai_roadmaps", ["requirement_set_id"])


def downgrade():
    op.drop_index("idx_roadmaps_requirement_set", table_name="pai_roadmaps")
    op.drop_column("pai_roadmaps", "requirement_set_id")
