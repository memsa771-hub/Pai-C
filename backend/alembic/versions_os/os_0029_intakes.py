"""P2-T8: intakes as rows and the expected fact slots of a rollover (P2 spec P2-D23, §4.8; R-61, R-62, R-63, R-66).

`os_intakes`: one row per region, family, term and year, with a state. `current` needs a recorded gate pass.
`os_fact_slots`: the (scope, ref, field, owner) keys a new intake expects, copied from the previous one with no values.

Revision ID: os_0029
Revises: os_0028
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os. Written on os_0025 as os_0026; renumbered to os_0029 (after
T5, T2 and T3) when merged into pai-connect.
"""

import sqlalchemy as sa

from alembic import op

revision = "os_0029"
down_revision = "os_0028"
branch_labels = None
depends_on = None

S = "os"


_CAUSES = ("'seed', 'manual', 'research', 'import', 'review', 'monitor', 'report', 'rollover'")


def upgrade() -> None:
    # D-t1-1: the term backfill leaves a revision, so `backfill` is an allowed cause (T1's check is replaced)
    op.drop_constraint("ck_os_fact_revisions_cause", "os_fact_revisions", schema=S)
    op.create_check_constraint("ck_os_fact_revisions_cause", "os_fact_revisions", f"cause IN ({_CAUSES}, 'backfill')",
                               schema=S)
    op.create_table(
        "os_intakes",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("region", sa.Text, nullable=False),
        sa.Column("family", sa.Text, nullable=False),
        sa.Column("term", sa.Text, nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="planned"),
        sa.Column("gate_passed_at", sa.DateTime(timezone=True)),
        sa.Column("opened_from_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_intakes.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "region", "family", "term", "year", name="uq_os_intakes_key"),
        sa.CheckConstraint("state IN ('planned', 'open', 'current', 'closed')", name="ck_os_intakes_state"),
        sa.CheckConstraint("term ~ '^[a-z_]+$'", name="ck_os_intakes_term"),
        sa.CheckConstraint("state <> 'current' OR gate_passed_at IS NOT NULL", name="ck_os_intakes_current_gate"),
        schema=S,
    )
    op.create_index("ix_os_intakes_term_year", "os_intakes", ["tenant_id", "term", "year"], schema=S)
    op.create_table(
        "os_fact_slots",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("intake_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_intakes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("owner_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("fact_class", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "intake_id", "scope", "ref", "field", "owner_ref", name="uq_os_fact_slots_key"),
        schema=S,
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM {S}.os_fact_revisions WHERE cause = 'backfill'")
    op.drop_constraint("ck_os_fact_revisions_cause", "os_fact_revisions", schema=S)
    op.create_check_constraint("ck_os_fact_revisions_cause", "os_fact_revisions", f"cause IN ({_CAUSES})", schema=S)
    op.drop_table("os_fact_slots", schema=S)
    op.drop_index("ix_os_intakes_term_year", "os_intakes", schema=S)
    op.drop_table("os_intakes", schema=S)
