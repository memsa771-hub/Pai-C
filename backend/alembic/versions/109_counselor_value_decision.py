"""Record the private conversation controller decision.

Revision ID: 109
Revises: 108
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "109"
down_revision = "108"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pai_counselor_turn_decisions", sa.Column("decision", JSONB(), nullable=True))


def downgrade():
    op.drop_column("pai_counselor_turn_decisions", "decision")
