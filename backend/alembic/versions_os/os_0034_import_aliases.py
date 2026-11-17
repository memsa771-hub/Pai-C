"""P2-T13: the import log records the alias files an import used, with their sha256 (P2 spec §4.6; master R-68, R-76).

Revision ID: os_0034
Revises: os_0033
Create Date: 2026-11-13

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "os_0034"
down_revision = "os_0033"
branch_labels = None
depends_on = None

S, T = "os", "os_imports"


def upgrade() -> None:
    op.add_column(T, sa.Column("aliases", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")), schema=S)


def downgrade() -> None:
    if op.get_bind().execute(sa.text(f"SELECT 1 FROM {S}.{T} WHERE aliases <> '[]'::jsonb LIMIT 1")).first():
        raise RuntimeError("os_0034 downgrade refused: imports that used alias files are logged (no silent loss)")
    op.drop_column(T, "aliases", schema=S)
