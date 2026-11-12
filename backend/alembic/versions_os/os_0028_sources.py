"""P2-T3: official-source allow-lists with runtime state, page snapshots and original files (P2 spec P2-D10, P2-D11;
R-24, R-71, R-29). New tables only: nothing existing changes, so with the guard off behaviour is as before.

<<<<<<<< HEAD:backend/alembic/versions_os/os_0027_sources.py
Revision ID: os_0027
Revises: os_0026
========
Revision ID: os_0028
Revises: os_0027
>>>>>>>> origin/pc/p2-t3-sources:backend/alembic/versions_os/os_0028_sources.py
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa

from alembic import op

<<<<<<<< HEAD:backend/alembic/versions_os/os_0027_sources.py
revision = "os_0027"
down_revision = "os_0026"
========
revision = "os_0028"
down_revision = "os_0027"
>>>>>>>> origin/pc/p2-t3-sources:backend/alembic/versions_os/os_0028_sources.py
branch_labels = None
depends_on = None

S = "os"
D, SN, F = "os_source_domains", "os_page_snapshots", "os_source_files"


def upgrade() -> None:
    op.create_table(
        D,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("region", sa.Text, nullable=False, server_default=""),
        sa.Column("family", sa.Text, nullable=False, server_default=""),
        sa.Column("route_key", sa.Text, nullable=False, server_default=""),
        sa.Column("body_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("tier", sa.Text),
        sa.Column("list_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.Text, nullable=False, server_default=""),
        sa.Column("state", sa.Text, nullable=False, server_default="active"),
        sa.Column("state_reason", sa.Text),
        sa.Column("state_since", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "domain", "region", "family", "route_key", name="uq_os_source_domains_entry"),
        sa.CheckConstraint("tier IS NULL OR tier IN ('regulator', 'board', 'admission_body', 'institution')",
                           name="ck_os_source_domains_tier"),
        sa.CheckConstraint("state IN ('active', 'suspect')", name="ck_os_source_domains_state"),
        schema=S,
    )
    op.create_index("ix_os_source_domains_domain", D, ["tenant_id", "domain"], schema=S)
    op.create_table(
        SN,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False, server_default=""),
        sa.Column("read_method", sa.Text, nullable=False, server_default="fetch"),
        sa.Column("language", sa.Text),
        sa.Column("links_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("links_off_list", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flagged", sa.Text),
        sa.Column("original_too_large", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "url", "sha256", name="uq_os_page_snapshots_url_hash"),
        sa.CheckConstraint("read_method IN ('fetch', 'render', 'ocr', 'human')",
                           name="ck_os_page_snapshots_read_method"),
        sa.CheckConstraint("language IS NULL OR language ~ '^[a-z]{2,3}$'", name="ck_os_page_snapshots_language"),
        schema=S,
    )
    op.create_index("ix_os_page_snapshots_url", SN, ["tenant_id", "url", "fetched_at"], schema=S)
    op.create_table(
        F,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger, sa.ForeignKey(f"{S}.{SN}.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "snapshot_id", name="uq_os_source_files_snapshot"),
        schema=S,
    )


def downgrade() -> None:
    conn = op.get_bind()
    for table in (F, SN, D):
        if conn.execute(sa.text(f"SELECT 1 FROM {S}.{table} LIMIT 1")).first():
<<<<<<<< HEAD:backend/alembic/versions_os/os_0027_sources.py
            raise RuntimeError(f"os_0027 downgrade refused: {table} holds rows (no silent loss)")
========
            raise RuntimeError(f"os_0028 downgrade refused: {table} holds rows (no silent loss)")
>>>>>>>> origin/pc/p2-t3-sources:backend/alembic/versions_os/os_0028_sources.py
    op.drop_table(F, schema=S)
    op.drop_table(SN, schema=S)
    op.drop_table(D, schema=S)
