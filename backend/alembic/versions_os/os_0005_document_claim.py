"""os_documents.claimed_by: the workflow that claimed a document for reading (Slice 3 Task 7).

The os.document `start` step claims a document (`uploaded` to `reading`). If the worker dies after that update
commits but before DBOS records the step, the step runs again: the claim names its workflow, so the same workflow
carries on and any other is refused (invariant 8).

Revision ID: os_0005
Revises: os_0004
Create Date: 2026-10-21

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0005"
down_revision = "os_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("os_documents", sa.Column("claimed_by", sa.Text), schema="os")


def downgrade() -> None:
    op.drop_column("os_documents", "claimed_by", schema="os")
