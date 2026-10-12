"""Record Voice counseling moves.

Revision ID: 106
Revises: 105
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "106"
down_revision = "105"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pai_counselor_turn_decisions", sa.Column("moves", JSONB(), nullable=True))


def downgrade():
    op.drop_column("pai_counselor_turn_decisions", "moves")
