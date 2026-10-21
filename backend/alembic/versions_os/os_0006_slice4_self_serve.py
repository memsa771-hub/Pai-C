"""Slice 4: programme requests, and what eligibility notes need (spec §3, S4-D7, S4-D8).

- os_programmes.status also allows `requested` (a student asked for it; researched once, shared).
- os_programme_requests: who asked for which programme, when (daily cap, audit).
- os_eligibility_seen: the last eligibility verdict a student was told about, per programme (notes on change).
- os_eligibility_notes: the change notes shown in the student's inbox.
No eligibility card is stored (S4-D3).

Revision ID: os_0006
Revises: os_0005
Create Date: 2026-10-22

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0006"
down_revision = "os_0005"
branch_labels = None
depends_on = None

S = "os"


def _status_check(values: tuple[str, ...]) -> None:
    op.drop_constraint("ck_os_programmes_status", "os_programmes", schema=S, type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint("ck_os_programmes_status", "os_programmes", f"status IN ({listed})", schema=S)


def upgrade() -> None:
    _status_check(("active", "excluded", "requested"))
    op.create_table(
        "os_programme_requests",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("route_key", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_index("ix_os_programme_requests_student", "os_programme_requests",
                    ["tenant_id", "student_ref", "created_at"], schema=S)
    op.create_table(
        "os_eligibility_seen",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "student_ref", "programme_ref", name="uq_os_eligibility_seen"),
        schema=S,
    )
    op.create_table(
        "os_eligibility_notes",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        schema=S,
    )
    op.create_index("ix_os_eligibility_notes_student", "os_eligibility_notes", ["tenant_id", "student_ref"],
                    schema=S)


def downgrade() -> None:
    op.drop_table("os_eligibility_notes", schema=S)
    op.drop_table("os_eligibility_seen", schema=S)
    op.drop_table("os_programme_requests", schema=S)
    op.execute(f"DELETE FROM {S}.os_programmes WHERE status = 'requested'")
    _status_check(("active", "excluded"))
