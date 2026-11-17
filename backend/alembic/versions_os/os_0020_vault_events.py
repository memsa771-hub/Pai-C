"""P1-T4 Task 1: the table `os_vault_events` keeps the Vault events the Counsellor sends (R-13, P1-D15): which
StudentFacts keys of a student changed at which Vault version (keys only, never values). One row per tenant, student
and version, so a repeat delivery stores nothing twice.

Revision ID: os_0020
Revises: os_0019
Create Date: 2026-11-05

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0020"
down_revision = "os_0019"
branch_labels = None
depends_on = None

S = "os"
T = "os_vault_events"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("vault_version", sa.Integer, nullable=False),
        sa.Column("keys", JSONB, nullable=False),
        sa.Column("event", JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "student_ref", "vault_version", name="uq_os_vault_events_version"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table(T, schema=S)
