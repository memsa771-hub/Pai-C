"""P2-T6: the import log (P2 spec §4.6 step 5; master R-68): one row per spreadsheet import, with the file's sha256,
who ran it, in which mode and what it did. Undo reads the revisions the import wrote (cause_ref `import-<id>`).

Revision ID: os_0027
Revises: os_0026
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "os_0027"
down_revision = "os_0026"
branch_labels = None
depends_on = None

S = "os"


def upgrade() -> None:
    op.create_table(
        "os_imports",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("decision_ref", sa.Text),
        sa.Column("batch_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("programmes_created", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("report_path", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("undone_at", sa.DateTime(timezone=True)),
        sa.Column("undone_by", sa.Text),
        sa.CheckConstraint("mode IN ('owner_accepted', 'reviewers')", name="ck_os_imports_mode"),
        sa.CheckConstraint("status IN ('running', 'done', 'failed', 'undone')", name="ck_os_imports_status"),
        sa.CheckConstraint("mode <> 'owner_accepted' OR decision_ref IS NOT NULL", name="ck_os_imports_decision"),
        schema=S,
    )
    # the same file cannot be imported twice at once: undo it first (a failed or undone import may be repeated)
    op.create_index("uq_os_imports_live", "os_imports", ["tenant_id", "sha256"], unique=True, schema=S,
                    postgresql_where=sa.text("status IN ('running', 'done')"))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.os_imports LIMIT 1")).first():
        raise RuntimeError("os_0027 downgrade refused: the import log holds rows (no silent loss)")
    op.drop_index("uq_os_imports_live", "os_imports", schema=S)
    op.drop_table("os_imports", schema=S)
