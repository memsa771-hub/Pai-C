"""Catalog-driven Vault item store, drop log and ranged budget definition.

Revision ID: 116
Revises: 115

The band and cover codes below are copied literally from the Vault catalog on
purpose: a migration must describe the schema as of today, even if the catalog
later changes (tests/test_vault_items_migration.py checks they still match).

pai_counselor_slot_answers needs no handling here; migration 102 already
dropped it.
"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None

BUDGET_SCHEMA = {
    "type": "object",
    "properties": {
        "band": {"type": "string", "enum": [
            "under_1_lakh", "1_3_lakh", "3_6_lakh", "6_10_lakh", "over_10_lakh", "not_sure"]},
        "min": {"type": "number", "minimum": 0},
        "max": {"type": "number", "minimum": 0},
        "amount": {"type": "number", "minimum": 0},
        "currency": {"type": "string"},
        "period": {"type": "string", "enum": ["per_year", "per_month", "total"]},
        "covers": {"type": "string", "enum": ["fees_only", "fees_and_living"]},
        "approximate": {"type": "boolean"},
        "possible_without_scholarship": {"type": "string", "enum": ["yes", "no", "not_sure"]},
    },
    "additionalProperties": False,
}


def upgrade():
    op.create_table(
        "pai_vault_items",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("type_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_language", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("conflict_state", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("valid_from", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("superseded_by", sa.Text()),
        sa.Column("candidate_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("level IN ('inferred', 'stated', 'shown', 'confirmed')", name="ck_vault_item_level"),
        sa.CheckConstraint("status IN ('active', 'superseded', 'retracted')", name="ck_vault_item_status"),
        sa.CheckConstraint("conflict_state IN ('none', 'in_question')", name="ck_vault_item_conflict_state"),
    )
    op.create_index("idx_vault_items_ws_type_status", "pai_vault_items", ["workspace_id", "item_type", "status"])
    op.create_table(
        "pai_vault_drops",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB()),
        sa.Column("source_ref", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("source IN ('chat', 'document', 'details', 'story')", name="ck_vault_drop_source"),
        sa.CheckConstraint("stage IN ('extract', 'normalize', 'validate')", name="ck_vault_drop_stage"),
    )
    op.create_index("idx_vault_drops_ws_created", "pai_vault_drops", ["workspace_id", "created_at"])
    # New VERSION of finance.budget: the old row stays (disabled) so facts
    # validated against it remain explainable.
    op.get_bind().execute(sa.text("""
        WITH retired AS (
            UPDATE pai_vault_field_definitions
            SET enabled = false
            WHERE key = 'finance.budget' AND enabled = true
            RETURNING *
        )
        INSERT INTO pai_vault_field_definitions (
            id, key, category, data_type, validation_schema, cardinality,
            conflict_policy, sensitivity, searchable, context_tags, required_for,
            profile_priority, extractable_from, verification_policy,
            source_policy, enabled, version, description
        )
        SELECT gen_random_uuid()::text, key, category, data_type,
               CAST(:schema AS jsonb), cardinality,
               conflict_policy, sensitivity, searchable, context_tags, required_for,
               profile_priority, extractable_from, verification_policy,
               source_policy, true, version + 1, description
        FROM retired
    """), {"schema": json.dumps(BUDGET_SCHEMA)})


def downgrade():
    connection = op.get_bind()
    connection.execute(sa.text("""
        DELETE FROM pai_vault_field_definitions
        WHERE key = 'finance.budget' AND version > 1
          AND version = (SELECT MAX(version) FROM pai_vault_field_definitions WHERE key = 'finance.budget')
    """))
    connection.execute(sa.text("""
        UPDATE pai_vault_field_definitions SET enabled = true
        WHERE key = 'finance.budget'
          AND version = (SELECT MAX(version) FROM pai_vault_field_definitions WHERE key = 'finance.budget')
    """))
    op.drop_index("idx_vault_drops_ws_created", table_name="pai_vault_drops")
    op.drop_table("pai_vault_drops")
    op.drop_index("idx_vault_items_ws_type_status", table_name="pai_vault_items")
    op.drop_table("pai_vault_items")
