"""Possibility fit indicators and the 360-degree analyzer as a source.

Revision ID: 112
Revises: 111

`fit` holds the analyzer's per-path indicators: what the student already has,
partly has, what blocks the path, and what is not known yet, each tied to the
student's own evidence. Additive only: existing rows get an empty list.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "112"
down_revision = "111"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pai_possibilities",
        sa.Column("fit", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.drop_constraint("ck_possibility_source", "pai_possibilities", type_="check")
    op.create_check_constraint("ck_possibility_source", "pai_possibilities",
        "source IN ('mirror','planner','student','analyzer')")


def downgrade():
    op.drop_constraint("ck_possibility_source", "pai_possibilities", type_="check")
    op.create_check_constraint("ck_possibility_source", "pai_possibilities",
        "source IN ('mirror','planner','student')")
    op.drop_column("pai_possibilities", "fit")
