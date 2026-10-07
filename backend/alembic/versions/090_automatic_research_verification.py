"""Replace manual review with recorded automatic verification checks.

Revision ID: 090
Revises: 089
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_institution_domains",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("institution_id", sa.Text(), sa.ForeignKey("pai_institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("institution_id", "domain", name="uq_institution_domain"),
    )
    op.create_index("idx_institution_domains_domain", "pai_institution_domains", ["domain"])
    op.add_column("pai_requirement_sets", sa.Column("verification_checks", JSONB(), nullable=False,
                                                    server_default=sa.text("'{}'")))
    op.add_column("pai_requirement_sets", sa.Column("cycle_label", sa.Text()))
    op.add_column("pai_requirement_sets", sa.Column("verified_at", sa.DateTime(timezone=True)))
    # Legacy manual approvals have none of the five recorded automatic checks.
    # They cannot retain a verified label after the verifier becomes the gate.
    op.execute("UPDATE pai_requirement_sets SET status = 'unconfirmed' WHERE status IN ('proposed', 'verified')")
    op.drop_constraint("ck_requirement_set_status", "pai_requirement_sets", type_="check")
    op.create_check_constraint("ck_requirement_set_status", "pai_requirement_sets",
                               "status IN ('unconfirmed', 'verified', 'expired')")
    op.drop_column("pai_requirement_sets", "reviewed_by")
    op.drop_column("pai_requirement_sets", "reviewed_at")


def downgrade():
    op.add_column("pai_requirement_sets", sa.Column("reviewed_by", sa.Text()))
    op.add_column("pai_requirement_sets", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_requirement_set_status", "pai_requirement_sets", type_="check")
    op.execute("UPDATE pai_requirement_sets SET status = 'proposed' WHERE status = 'unconfirmed'")
    op.create_check_constraint("ck_requirement_set_status", "pai_requirement_sets",
                               "status IN ('proposed', 'verified', 'expired')")
    op.drop_column("pai_requirement_sets", "verified_at")
    op.drop_column("pai_requirement_sets", "cycle_label")
    op.drop_column("pai_requirement_sets", "verification_checks")
    op.drop_index("idx_institution_domains_domain", table_name="pai_institution_domains")
    op.drop_table("pai_institution_domains")
