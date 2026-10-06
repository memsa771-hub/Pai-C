"""Durable confirmation and queued research state on the Counselor Journey.

Revision ID: 086
Revises: 085
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pai_student_journeys", sa.Column("counselor_summary_draft", JSONB(), nullable=True))
    op.add_column("pai_student_journeys", sa.Column("research_request", JSONB(), nullable=True))


def downgrade():
    op.drop_column("pai_student_journeys", "research_request")
    op.drop_column("pai_student_journeys", "counselor_summary_draft")
