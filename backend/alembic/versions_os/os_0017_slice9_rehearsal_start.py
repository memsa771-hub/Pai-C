"""Slice 9a Task 11: a rehearsal may start on a set day, so its clock offset can be negative (spec §2.1-2.2).

The admin `start` call sets the offset once on a clean rehearsal clock so that the shared clock's today is the chosen
day, which may lie before the real date (the short CI rehearsal starts on 1 Dec 2026 whatever the real date). `advance`
stays forward-only.

Revision ID: os_0017
Revises: os_0016
Create Date: 2026-10-28

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

from alembic import op

revision = "os_0017"
down_revision = "os_0016"
branch_labels = None
depends_on = None

S = "os"
T = "os_rehearsal_clock"
CK = "ck_os_rehearsal_clock_offset"


def upgrade() -> None:
    op.drop_constraint(CK, T, schema=S, type_="check")


def downgrade() -> None:
    op.execute(f"UPDATE {S}.{T} SET offset_seconds = 0 WHERE offset_seconds < 0")
    op.create_check_constraint(CK, T, "offset_seconds >= 0", schema=S)
