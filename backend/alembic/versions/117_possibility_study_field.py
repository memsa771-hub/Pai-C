"""Possibilities name a real field of study.

Revision ID: 117
Revises: 116

`study_field` holds the study field an analyzer path names (key, ISCED code
for PAI OS, whether it needs checking for the student's group, the group a
Matric student would need), or {"outdated": true} for a saved path from before
paths were fields of study. Additive only: existing rows stay null.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "117"
down_revision = "116"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pai_possibilities", sa.Column("study_field", JSONB(), nullable=True))


def downgrade():
    op.drop_column("pai_possibilities", "study_field")
