"""Private Counselor Notebook and append-only history.

Revision ID: 096
Revises: 095
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "counselor_notebooks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("notebook", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", sa.Text(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_counselor_notebook_version"),
    )
    op.create_table(
        "counselor_notebook_history",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("notebook", JSONB(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "version", name="uq_counselor_notebook_history_version"),
        sa.CheckConstraint("version > 0", name="ck_counselor_notebook_history_version"),
    )


def downgrade():
    op.drop_table("counselor_notebook_history")
    op.drop_table("counselor_notebooks")
