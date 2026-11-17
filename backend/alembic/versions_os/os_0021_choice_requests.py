"""P1-T6 Task 1: proposals can ask the Counsellor for a choice change (R-07) and a self-serve plan can be adopted
(R-08). `os_proposals` gets the status `requested`, the source `student` (the builder's own swap and remove), the
decision version the proposal was made against, the version the Counsellor wrote, and the answer it gave. The new
table `os_plan_adoptions` keeps the student's agreement to adopt an open self-serve plan (P1 plan D-x1, D-x6).

Revision ID: os_0021
Revises: os_0020
Create Date: 2026-11-06

Downgrade: a `requested` proposal becomes `expired` (the old status list has no `requested`). A proposal with
source `student` cannot be kept under the old source check and deleting it would cascade into os_plan_overrides, so
the downgrade raises RuntimeError and changes nothing while any exists.

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0021"
down_revision = "os_0020"
branch_labels = None
depends_on = None

S = "os"
P = "os_proposals"
OLD_STATUSES = ("applied", "pending", "accepted", "declined", "expired", "refused")
NEW_STATUSES = (*OLD_STATUSES, "requested")
OLD_SOURCES = ("rules", "supervisor")
NEW_SOURCES = (*OLD_SOURCES, "student")
OUTCOMES = ("written", "duplicate", "stale", "refused")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint("ck_os_proposals_status", P, schema=S, type_="check")
    op.create_check_constraint("ck_os_proposals_status", P, _in("status", NEW_STATUSES), schema=S)
    op.drop_constraint("ck_os_proposals_source", P, schema=S, type_="check")
    op.create_check_constraint("ck_os_proposals_source", P, _in("source", NEW_SOURCES), schema=S)
    op.add_column(P, sa.Column("base_decision_version", sa.Integer), schema=S)  # NULL: made before os_0021
    op.add_column(P, sa.Column("requested_version", sa.Integer), schema=S)  # the n+1 the Counsellor wrote
    op.add_column(P, sa.Column("request_outcome", sa.Text), schema=S)
    op.create_check_constraint("ck_os_proposals_request_outcome", P,
                               _in("request_outcome", OUTCOMES), schema=S)  # NULL passes a CHECK: no answer yet
    op.create_table(
        "os_plan_adoptions",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_sha256", sa.Text, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("adopted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "plan_id", name="uq_os_plan_adoptions_plan"),
        schema=S,
    )


def downgrade() -> None:
    kept = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {S}.{P} WHERE source = 'student'")).scalar()
    if kept:
        raise RuntimeError(f"os_0021 downgrade refused: {kept} proposal(s) have source 'student'; deleting them would "
                           "also delete their plan overrides. Resolve them by hand first.")
    op.drop_table("os_plan_adoptions", schema=S)
    op.drop_constraint("ck_os_proposals_request_outcome", P, schema=S, type_="check")
    op.drop_column(P, "request_outcome", schema=S)
    op.drop_column(P, "requested_version", schema=S)
    op.drop_column(P, "base_decision_version", schema=S)
    op.execute(f"UPDATE {S}.{P} SET status = 'expired' WHERE status = 'requested'")  # the old checks have no `requested`
    op.drop_constraint("ck_os_proposals_source", P, schema=S, type_="check")
    op.create_check_constraint("ck_os_proposals_source", P, _in("source", OLD_SOURCES), schema=S)
    op.drop_constraint("ck_os_proposals_status", P, schema=S, type_="check")
    op.create_check_constraint("ck_os_proposals_status", P, _in("status", OLD_STATUSES), schema=S)
