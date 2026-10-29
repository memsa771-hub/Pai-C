"""The student's chat language on the workspace (BETA_CONVERSATION_SPEC 2.5).

Revision ID: 123
Revises: 122

Two nullable JSONB columns on `workspaces`:
- `chat_language`: {code, script} of the student's latest chat message, read
  by the opening, the Writer, the Mirror text and the messages PAI posts;
- `rendered_copy`: fixed English copy rendered in a chat language, keyed by
  copy key, text digest and language, so each is rendered once.
Additive only; NULL means English.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "123"
down_revision = "122"
branch_labels = depends_on = None


def upgrade():
    op.add_column("workspaces", sa.Column("chat_language", JSONB(), nullable=True))
    op.add_column("workspaces", sa.Column("rendered_copy", JSONB(), nullable=True))


def downgrade():
    op.drop_column("workspaces", "rendered_copy")
    op.drop_column("workspaces", "chat_language")
