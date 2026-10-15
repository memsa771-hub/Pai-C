"""Add request intake metadata, preserving existing research statuses.

Revision ID: 108
Revises: 107
"""
from alembic import op
import sqlalchemy as sa

revision = "108"
down_revision = "107"
branch_labels = depends_on = None


def upgrade():
    op.add_column("counselor_noted_questions", sa.Column("kind", sa.Text(), nullable=False, server_default="information"))
    op.add_column("counselor_noted_questions", sa.Column("needs_research", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("counselor_noted_questions", sa.Column("answered_event_id", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("counselor_noted_questions", "answered_event_id")
    op.drop_column("counselor_noted_questions", "needs_research")
    op.drop_column("counselor_noted_questions", "kind")
