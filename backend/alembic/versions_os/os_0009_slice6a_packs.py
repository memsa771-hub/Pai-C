"""Slice 6a: the application pack (spec §3): rendered pack files (one per SHA-256 per student), the student's
per-programme ticks and added items, and where a profile value came from (a document, or typed by the student).

Revision ID: os_0009
Revises: os_0008
Create Date: 2026-10-22

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0009"
down_revision = "os_0008"
branch_labels = None
depends_on = None

S = "os"


def _id():
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", sa.Text, nullable=False)


def _now(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "os_pack_files", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("item_key", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("pages", sa.Integer, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        _now("created_at"),
        sa.UniqueConstraint("tenant_id", "student_ref", "sha256", name="uq_os_pack_files_sha"),
        schema=S)
    op.create_table(
        "os_pack_items", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("item_key", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("label", sa.Text),
        _now("at"),
        sa.CheckConstraint("kind IN ('added', 'ticked')", name="ck_os_pack_items_kind"),
        sa.UniqueConstraint("tenant_id", "student_ref", "programme_ref", "item_key", "kind", name="uq_os_pack_items"),
        schema=S)
    op.add_column("os_profile_values", sa.Column("source", sa.Text, nullable=False, server_default="document"),
                  schema=S)
    op.create_check_constraint("ck_os_profile_values_source", "os_profile_values", "source IN ('document', 'entered')",
                               schema=S)


def downgrade() -> None:
    op.drop_constraint("ck_os_profile_values_source", "os_profile_values", type_="check", schema=S)
    op.drop_column("os_profile_values", "source", schema=S)
    op.drop_table("os_pack_items", schema=S)
    op.drop_table("os_pack_files", schema=S)
