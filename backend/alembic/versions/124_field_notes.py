"""Shared field notes for the path engine (BETA_CONVERSATION_SPEC 3.1).

Revision ID: 124
Revises: 123

`pai_field_notes` holds one researched note per study field and country: the
sections (what you study, a work day, entry, jobs and demand, myths), each fact
with a verbatim quote and its source URL, the pages read, a confidence and when
it was researched. Not per workspace: the path analyzer and path explain of
every student read the same note. Additive only.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "124"
down_revision = "123"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "pai_field_notes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("field_key", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("note", JSONB(), nullable=False),
        sa.Column("sources", JSONB(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("researched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("field_key", "country", name="uq_field_notes_field_country"),
    )


def downgrade():
    op.drop_table("pai_field_notes")
