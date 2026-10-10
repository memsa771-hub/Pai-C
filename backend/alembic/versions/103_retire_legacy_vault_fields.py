"""Retire legacy scalar education/test definitions without removing history.

Revision ID: 103
Revises: 102
"""
from alembic import op
import sqlalchemy as sa

revision = "103"
down_revision = "102"
branch_labels = depends_on = None


def _set_enabled(enabled):
    definitions = sa.table("pai_vault_field_definitions", sa.column("key", sa.Text()),
                           sa.column("enabled", sa.Boolean()))
    op.get_bind().execute(definitions.update().where(definitions.c.key.in_(
        ("education.cgpa", "education.backlogs", "tests.ielts.score"))).values(enabled=enabled))


def upgrade():
    _set_enabled(False)


def downgrade():
    _set_enabled(True)
