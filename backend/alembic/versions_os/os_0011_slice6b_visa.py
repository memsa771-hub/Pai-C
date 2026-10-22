"""Slice 6b: the visa file is a second kind of pack (spec S6b-D2, D8): artifact kind `visa`, and the student's choice
of programme and other proof of funds.

Revision ID: os_0011
Revises: os_0010
Create Date: 2026-10-23

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0011"
down_revision = "os_0010"
branch_labels = None
depends_on = None

S = "os"
KINDS_OLD, KINDS_NEW = ("sop", "cv", "pack"), ("sop", "cv", "pack", "visa")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _swap(values: tuple[str, ...]) -> None:
    op.drop_constraint("ck_os_artifacts_kind", "os_artifacts", type_="check", schema=S)
    op.create_check_constraint("ck_os_artifacts_kind", "os_artifacts", _in("kind", values), schema=S)


def upgrade() -> None:
    _swap(KINDS_NEW)
    op.create_table(
        "os_visa_choices",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text),
        sa.Column("reduction", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "student_ref", name="uq_os_visa_choices"),
        sa.CheckConstraint("reduction >= 0", name="ck_os_visa_choices_reduction"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("os_visa_choices", schema=S)
    op.execute(f"DELETE FROM {S}.os_artifacts WHERE kind = 'visa'")
    _swap(KINDS_OLD)
