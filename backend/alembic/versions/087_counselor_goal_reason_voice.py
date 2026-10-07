"""Source goal motivation from a durable student statement across alternatives.

Revision ID: 087
Revises: 086
"""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None

KEY = "discovery.goal_reason"
ROW_ID = str(uuid5(NAMESPACE_URL, "pai-counselor-087:goal_reason"))


def upgrade():
    connection = op.get_bind()
    old = connection.execute(sa.text("""
        SELECT tier, priority, applicability, question, question_intent,
               canonical_questions, accepts_unknown
        FROM pai_profile_requirements WHERE key = :key AND version = 1
    """), {"key": KEY}).mappings().one()
    connection.execute(sa.text("""
        INSERT INTO pai_profile_requirements
          (id, key, stage, tier, source_type, source_key, source_path,
           selector, applicability, question, question_intent,
           canonical_questions, accepts_unknown, priority, enabled, version)
        VALUES (:id, :key, 'direction', :tier, 'record_field',
                'student_voice_statement', 'statement', 'any',
                CAST(:applicability AS jsonb), :question, :intent,
                CAST(:canonical AS jsonb), :accepts_unknown, :priority, TRUE, 2)
        ON CONFLICT (key, version) DO NOTHING
    """), {"id": ROW_ID, "key": KEY, "tier": old["tier"], "priority": old["priority"],
           "applicability": json.dumps(old["applicability"] or {}),
           "question": old["question"], "intent": old["question_intent"],
           "canonical": json.dumps(old["canonical_questions"] or {}, ensure_ascii=False),
           "accepts_unknown": old["accepts_unknown"]})


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM pai_profile_requirements WHERE id = :id"),
                          {"id": ROW_ID})
