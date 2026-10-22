"""os_eligibility_seen per plan (Slice 4 final review).

The last verdict a student was told about was kept per (student, programme). A student can have the same programme
in two plans (two intakes) with two different verdicts, so every evaluation looked like a change and wrote a false
note. It is now kept per (plan, programme). Existing rows are only "last told" markers and are dropped: the next
evaluation records them again without a note.

Revision ID: os_0007
Revises: os_0006
Create Date: 2026-10-22

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0007"
down_revision = "os_0006"
branch_labels = None
depends_on = None

S = "os"


def upgrade() -> None:
    op.execute(f"DELETE FROM {S}.os_eligibility_seen")
    op.drop_constraint("uq_os_eligibility_seen", "os_eligibility_seen", schema=S, type_="unique")
    op.add_column("os_eligibility_seen", sa.Column("plan_id", sa.BigInteger, nullable=False), schema=S)
    op.create_foreign_key("os_eligibility_seen_plan_id_fkey", "os_eligibility_seen", "os_plans", ["plan_id"], ["id"],
                          source_schema=S, referent_schema=S, ondelete="CASCADE")
    op.create_unique_constraint("uq_os_eligibility_seen", "os_eligibility_seen", ["tenant_id", "plan_id", "programme_ref"],
                                schema=S)


def downgrade() -> None:
    op.execute(f"DELETE FROM {S}.os_eligibility_seen")
    op.drop_constraint("uq_os_eligibility_seen", "os_eligibility_seen", schema=S, type_="unique")
    op.drop_constraint("os_eligibility_seen_plan_id_fkey", "os_eligibility_seen", schema=S, type_="foreignkey")
    op.drop_column("os_eligibility_seen", "plan_id", schema=S)
    op.create_unique_constraint("uq_os_eligibility_seen", "os_eligibility_seen", ["tenant_id", "student_ref", "programme_ref"],
                                schema=S)
