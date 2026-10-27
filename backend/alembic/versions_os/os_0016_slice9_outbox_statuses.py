"""Slice 9a: outbox statuses `blocked` (not on the email allow-list) and `failed` (provider refused) (spec §3.3).

Revision ID: os_0016
Revises: os_0015
Create Date: 2026-10-27

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

from alembic import op

revision = "os_0016"
down_revision = "os_0015"
branch_labels = None
depends_on = None

S = "os"
T = "os_outbox"
CK = "ck_os_outbox_status"


def upgrade() -> None:
    op.drop_constraint(CK, T, schema=S, type_="check")
    op.create_check_constraint(CK, T, "status IN ('pending', 'sent', 'skipped', 'blocked', 'failed')", schema=S)


def downgrade() -> None:
    op.execute(f"UPDATE {S}.{T} SET status = 'skipped' WHERE status IN ('blocked', 'failed')")
    op.drop_constraint(CK, T, schema=S, type_="check")
    op.create_check_constraint(CK, T, "status IN ('pending', 'sent', 'skipped')", schema=S)
