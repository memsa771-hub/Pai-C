"""P2-T12: consistency cases for rules 9-12 of master §9.3 (what a student is shown: allow-list, high-stakes, intake year,
suspect domain). Widens the rule check from 1-8 to 1-12. No data changes.

Revision ID: os_0033
Revises: os_0032
Create Date: 2026-11-08

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa

from alembic import op

revision = "os_0033"
down_revision = "os_0032"
branch_labels = None
depends_on = None

S, T, CK = "os", "os_consistency_cases", "ck_os_consistency_cases_rule"


def upgrade() -> None:
    op.drop_constraint(CK, T, schema=S)
    op.create_check_constraint(CK, T, "rule BETWEEN 1 AND 12", schema=S)


def downgrade() -> None:
    if op.get_bind().execute(sa.text(f"SELECT 1 FROM {S}.{T} WHERE rule > 8 LIMIT 1")).first():
        raise RuntimeError("os_0033 downgrade refused: cases for rules 9-12 exist (no silent loss)")
    op.drop_constraint(CK, T, schema=S)
    op.create_check_constraint(CK, T, "rule BETWEEN 1 AND 8", schema=S)
