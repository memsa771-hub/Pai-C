"""Slice 9a: pilot consent (spec §3.2, §4): one row per student and terms version they agreed to.

Revision ID: os_0015
Revises: os_0014
Create Date: 2026-10-27

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa

from alembic import op

revision = "os_0015"
down_revision = "os_0014"
branch_labels = None
depends_on = None

S = "os"


def upgrade() -> None:
    op.create_table(
        "os_consents",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("terms_version", sa.Integer, nullable=False),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "student_ref", "terms_version", name="uq_os_consents_student_version"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("os_consents", schema=S)
