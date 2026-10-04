"""Durable Vault assertions, evidence and cross-domain relationships.

Revision ID: 078
Revises: 077
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pai_memory_candidates", sa.Column("input_channel", sa.Text()))
    op.add_column("pai_memory_candidates", sa.Column("effective_at", sa.DateTime(timezone=True)))
    op.add_column("pai_vault_facts", sa.Column("effective_at", sa.DateTime(timezone=True)))
    op.add_column("pai_profile_issues", sa.Column("conflict_kind", sa.Text()))
    op.add_column("pai_vault_field_definitions", sa.Column("source_policy", postgresql.JSONB()))
    # Introduce domain policies as NEW field-definition versions. Old versions
    # stay available to explain facts validated before this migration.
    op.execute("""
        WITH retired AS (
            UPDATE pai_vault_field_definitions
            SET enabled = false
            WHERE enabled = true AND source_policy IS NULL
              AND category IN ('preferences', 'career', 'mobility', 'location')
            RETURNING *
        )
        INSERT INTO pai_vault_field_definitions (
            id, key, category, data_type, validation_schema, cardinality,
            conflict_policy, sensitivity, searchable, context_tags, required_for,
            profile_priority, extractable_from, verification_policy,
            source_policy, enabled, version, description
        )
        SELECT gen_random_uuid()::text, key, category, data_type,
               validation_schema, cardinality, conflict_policy, sensitivity,
               searchable, context_tags, required_for, profile_priority,
               extractable_from, verification_policy,
               CASE WHEN category = 'location'
                    THEN jsonb_build_object('temporal_change', 'student_transition')
                    ELSE jsonb_build_object(
                        'allowed_sources', jsonb_build_array('user_explicit', 'conversation'),
                        'authority_rank', jsonb_build_object(
                            'user_explicit', 100, 'conversation', 80))
               END,
               true, version + 1, description
        FROM retired
    """)
    op.create_table(
        "pai_vault_assertions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_user_id", sa.Text()),
        sa.Column("candidate_id", sa.Text(), sa.ForeignKey("pai_memory_candidates.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB()),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_actor", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text()),
        sa.Column("source_ref", sa.Text()),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("language", sa.Text()),
        sa.Column("trust_metadata", postgresql.JSONB()),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("decision", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("canonical_type", sa.Text()),
        sa.Column("canonical_id", sa.Text()),
        sa.Column("decision_reason", sa.Text()),
    )
    op.create_index("idx_vault_assertion_ws_domain", "pai_vault_assertions", ["workspace_id", "domain", "captured_at"])
    op.create_index("idx_vault_assertion_source", "pai_vault_assertions", ["workspace_id", "source_event_id"])
    op.create_table(
        "pai_vault_evidence",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text()),
        sa.Column("authority", sa.Text()),
        sa.Column("locator", sa.Text()),
        sa.Column("quote", sa.Text()),
        sa.Column("verification", sa.Text(), nullable=False, server_default=sa.text("'unverified'")),
        sa.Column("sensitivity", sa.Text(), nullable=False, server_default=sa.text("'sensitive'")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("uq_vault_evidence_ws_fingerprint", "pai_vault_evidence", ["workspace_id", "fingerprint"], unique=True)
    op.create_table(
        "pai_vault_assertion_evidence",
        sa.Column("assertion_id", sa.Text(), sa.ForeignKey("pai_vault_assertions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("evidence_id", sa.Text(), sa.ForeignKey("pai_vault_evidence.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "pai_vault_relations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("assertion_id", sa.Text(), sa.ForeignKey("pai_vault_assertions.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_vault_relations_ws_subject", "pai_vault_relations", ["workspace_id", "subject_type", "subject_id"])
    op.create_index("idx_vault_relations_ws_object", "pai_vault_relations", ["workspace_id", "object_type", "object_id"])
    op.create_index("uq_vault_relation_edge", "pai_vault_relations", ["workspace_id", "subject_type", "subject_id", "predicate", "object_type", "object_id"], unique=True)
    op.create_table(
        "pai_student_credentials",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_user_id", sa.Text()),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("claim_origin", sa.Text(), nullable=False),
        sa.Column("capture_method", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default=sa.text("'self_reported'")),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("credential_type", sa.Text(), nullable=False),
        sa.Column("original_type", sa.Text()),
        sa.Column("issuer", sa.Text()),
        sa.Column("jurisdiction", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column("issued_at", sa.Text()),
        sa.Column("valid_from", sa.Text()),
        sa.Column("valid_until", sa.Text()),
        sa.Column("raw_document_ref", sa.Text()),
        sa.Column("credential_format", sa.Text()),
        sa.Column("credential_identifier", sa.Text()),
        sa.Column("claims", postgresql.JSONB()),
    )
    op.create_index("idx_pai_credentials_ws", "pai_student_credentials", ["workspace_id", "status"])


def downgrade():
    op.drop_table("pai_student_credentials")
    op.drop_table("pai_vault_relations")
    op.drop_table("pai_vault_assertion_evidence")
    op.drop_table("pai_vault_evidence")
    op.drop_table("pai_vault_assertions")
    op.drop_column("pai_vault_field_definitions", "source_policy")
    op.drop_column("pai_memory_candidates", "input_channel")
    op.drop_column("pai_memory_candidates", "effective_at")
    op.drop_column("pai_vault_facts", "effective_at")
    op.drop_column("pai_profile_issues", "conflict_kind")
