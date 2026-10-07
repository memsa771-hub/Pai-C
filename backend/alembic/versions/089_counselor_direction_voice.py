"""Keep direction answers durable even before a goal record is chosen.

Revision ID: 089
Revises: 088
"""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None

SLOTS = ("field_interest", "envisioned_outcome", "timing")


def upgrade():
    connection = op.get_bind()
    for slot in SLOTS:
        key = f"discovery.{slot}"
        prior = connection.execute(sa.text("""
            SELECT stage, tier, priority, applicability, question, question_intent,
                   canonical_questions, accepts_unknown
            FROM pai_profile_requirements WHERE key = :key AND version = 1
        """), {"key": key}).mappings().one()
        connection.execute(sa.text("""
            INSERT INTO pai_profile_requirements
              (id, key, stage, tier, source_type, source_key, source_path,
               selector, applicability, question, question_intent,
               canonical_questions, accepts_unknown, priority, enabled, version)
            VALUES (:id, :key, :stage, :tier, 'record_field',
                    'student_voice_statement', 'statement', 'any',
                    CAST(:applicability AS jsonb), :question, :intent,
                    CAST(:canonical AS jsonb), :accepts_unknown, :priority, TRUE, 2)
            ON CONFLICT (key, version) DO NOTHING
        """), {
            "id": str(uuid5(NAMESPACE_URL, f"pai-counselor-089:{slot}")),
            "key": key, "stage": prior["stage"], "tier": prior["tier"],
            "priority": prior["priority"],
            "applicability": json.dumps(prior["applicability"] or {}),
            "question": prior["question"], "intent": prior["question_intent"],
            "canonical": json.dumps(prior["canonical_questions"] or {}, ensure_ascii=False),
            "accepts_unknown": prior["accepts_unknown"],
        })


def downgrade():
    connection = op.get_bind()
    for slot in SLOTS:
        connection.execute(sa.text("DELETE FROM pai_profile_requirements WHERE id = :id"), {
            "id": str(uuid5(NAMESPACE_URL, f"pai-counselor-089:{slot}"))})
