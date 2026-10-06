"""Profile foundation response states and revised critical requirements.

Revision ID: 081
Revises: 080
"""

from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_profile_field_responses",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "status IN ('pending', 'valid_unknown', 'not_applicable', 'declined', 'deferred')",
            name="ck_profile_field_response_status",
        ),
        sa.UniqueConstraint("workspace_id", "requirement_key", name="uq_profile_field_response"),
    )

    # Version rather than mutate the original policy. An undecided student can
    # complete their academic foundation before choosing a goal. The goal is
    # still collected later during discovery.
    changes = (
        ("goal.active", "enrichment", 90),
        ("education.status", "critical", 85),
        ("education.level", "critical", 80),
        ("education.undergraduate_history", "critical", 75),
        ("education.pre_university_history", "critical", 70),
    )
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO pai_profile_requirements
            (id, key, tier, source_type, source_key, selector, question,
             priority, enabled, version)
        VALUES (:id, 'identity.status_category', 'critical', 'vault_fact',
                'identity.status_category', 'any',
                'Are you currently studying, working, or in another situation?',
                95, TRUE, 1)
        ON CONFLICT (key, version) DO NOTHING
    """), {"id": str(uuid5(NAMESPACE_URL, "pai-profile-foundation-081:identity.status_category"))})
    for key, tier, priority in changes:
        row = connection.execute(sa.text("""
            SELECT * FROM pai_profile_requirements
            WHERE key = :key AND enabled = TRUE
            ORDER BY version DESC LIMIT 1
        """), {"key": key}).mappings().first()
        if row is None:
            continue
        migration_id = str(uuid5(NAMESPACE_URL, f"pai-profile-foundation-081:{key}"))
        connection.execute(sa.text("""
            INSERT INTO pai_profile_requirements
                (id, key, tier, source_type, source_key, source_path, selector,
                 applicability, question, priority, enabled, version)
            SELECT :id, key, :tier, source_type, source_key, source_path,
                   selector,
                   CASE WHEN key IN ('education.status', 'education.level')
                        THEN jsonb_build_object('record_exists:education', TRUE)
                        ELSE applicability END,
                   question, :priority, TRUE, version + 1
            FROM pai_profile_requirements WHERE id = :previous_id
        """), {"id": migration_id, "previous_id": row["id"],
                "tier": tier, "priority": priority})


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM pai_profile_requirements WHERE id = :id"),
        {"id": str(uuid5(NAMESPACE_URL, "pai-profile-foundation-081:identity.status_category"))},
    )
    for key in (
        "goal.active", "education.status", "education.level",
        "education.undergraduate_history", "education.pre_university_history",
    ):
        connection.execute(
            sa.text("DELETE FROM pai_profile_requirements WHERE id = :id"),
            {"id": str(uuid5(NAMESPACE_URL, f"pai-profile-foundation-081:{key}"))},
        )
    op.drop_table("pai_profile_field_responses")
