"""Persist sourced answers to deferred student questions.

Revision ID: 099
Revises: 098
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "099"
down_revision = "098"
branch_labels = depends_on = None


def upgrade():
    op.add_column("counselor_noted_questions", sa.Column("fact_id", sa.Text(), nullable=True))
    op.add_column("counselor_noted_questions", sa.Column("answer", JSONB(), nullable=True))


def downgrade():
    op.drop_column("counselor_noted_questions", "answer")
    op.drop_column("counselor_noted_questions", "fact_id")
