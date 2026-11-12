"""P2-T4: how a cached page was read, and sources that could not be read (P2 spec §4.3; R-74, R-29, R-72).
`os_pages` gains `read_method` (default 'fetch') and `language`, so a cached OCR page is never mistaken for a
fetched one. New table `os_not_readable`.

Revision ID: os_0030
Revises: os_0029
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa

from alembic import op

revision = "os_0030"
down_revision = "os_0029"
branch_labels = None
depends_on = None

S = "os"
N = "os_not_readable"


def upgrade() -> None:
    # script tags (four letters, e.g. `arab`) are allowed where a page or snapshot has no language evidence (T4 review)
    op.drop_constraint("ck_os_page_snapshots_language", "os_page_snapshots", schema=S)
    op.create_check_constraint("ck_os_page_snapshots_language", "os_page_snapshots",
                               "language IS NULL OR language ~ '^[a-z]{2,4}$'", schema=S)
    op.add_column("os_pages", sa.Column("read_method", sa.Text, nullable=False, server_default="fetch"), schema=S)
    op.add_column("os_pages", sa.Column("language", sa.Text), schema=S)
    op.create_check_constraint("ck_os_pages_read_method", "os_pages",
                               "read_method IN ('fetch', 'render', 'ocr', 'human')", schema=S)
    op.create_table(
        N,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("field", sa.Text, nullable=False, server_default=""),
        sa.Column("intake_year", sa.Integer, nullable=False, server_default="0"),
        sa.Column("snapshot_id", sa.BigInteger),
        sa.Column("state", sa.Text, nullable=False, server_default="open"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "url", "programme_ref", "field", "intake_year", name="uq_os_not_readable"),
        sa.CheckConstraint("state IN ('open', 'collected', 'readable')", name="ck_os_not_readable_state"),
        schema=S,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.{N} LIMIT 1")).first():
        raise RuntimeError("os_0030 downgrade refused: os_not_readable holds rows (no silent loss)")
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.os_pages WHERE read_method <> 'fetch' LIMIT 1")).first():
        raise RuntimeError("os_0030 downgrade refused: cached pages record how they were read")
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.os_page_snapshots WHERE length(language) = 4 LIMIT 1")).first():
        raise RuntimeError("os_0030 downgrade refused: snapshots carry script tags")
    op.drop_constraint("ck_os_page_snapshots_language", "os_page_snapshots", schema=S)
    op.create_check_constraint("ck_os_page_snapshots_language", "os_page_snapshots",
                               "language IS NULL OR language ~ '^[a-z]{2,3}$'", schema=S)
    op.drop_table(N, schema=S)
    op.drop_constraint("ck_os_pages_read_method", "os_pages", schema=S)
    op.drop_column("os_pages", "language", schema=S)
    op.drop_column("os_pages", "read_method", schema=S)
