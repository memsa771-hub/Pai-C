"""Slice 9a: the rehearsal clock (spec §2.2, §4): one stored offset per tenant, read only in rehearsal mode.

Revision ID: os_0014
Revises: os_0013
Create Date: 2026-10-27

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa

from alembic import op

revision = "os_0014"
down_revision = "os_0013"
branch_labels = None
depends_on = None

S = "os"


def upgrade() -> None:
    op.create_table(
        "os_rehearsal_clock",
        sa.Column("tenant_id", sa.Text, primary_key=True),
        sa.Column("offset_seconds", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("offset_seconds >= 0", name="ck_os_rehearsal_clock_offset"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("os_rehearsal_clock", schema=S)
