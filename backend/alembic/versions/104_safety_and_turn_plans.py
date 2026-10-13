"""Safety classification metadata for Counselor turns.

Revision ID: 104
Revises: 103
"""
from alembic import op
import sqlalchemy as sa
revision = "104"
down_revision = "103"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pai_counselor_turn_decisions", sa.Column("safety_level", sa.Text(), nullable=True))
    op.add_column("pai_counselor_turn_decisions", sa.Column("safety_category", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("pai_counselor_turn_decisions", "safety_category")
    op.drop_column("pai_counselor_turn_decisions", "safety_level")
