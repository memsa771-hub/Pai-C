"""Counselor journey stages and goal discovery questions.

Revision ID: 082
Revises: 081
"""

from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None

LEGACY = ("ORIENTING", "UNDERSTANDING", "ALIGNING", "PLANNING", "ACTING",
          "REVIEWING", "COMPLETED")
COUNSELOR = ("IDENTITY", "FOUNDATION", "DIRECTION", "RESEARCHING",
             "ASSESSING", "NEEDS_INFO", "PROPOSED", "CHOSEN")
QUESTIONS = (
    ("goal.stated_preference", "details.stated_preference",
     "Which direction are you considering?", 98, "important", "any"),
    ("goal.underlying_objective", "details.underlying_objective",
     "What would that direction help you achieve?", 97, "important", "any"),
    ("goal.constraints", "details.constraints",
     "What limits should we account for as we explore it?", 85, "important", "any_present"),
    ("goal.drivers", "details.drivers",
     "What matters most about that direction to you?", 75, "enrichment", "any"),
)


def _check(values):
    return "current_stage IS NULL OR current_stage IN (" + ",".join(
        f"'{value}'" for value in values) + ")"


def upgrade():
    op.drop_constraint("ck_profile_requirement_selector", "pai_profile_requirements", type_="check")
    op.create_check_constraint("ck_profile_requirement_selector", "pai_profile_requirements",
                               "selector IN ('any', 'current_or_highest', 'any_present')")
    op.drop_constraint("ck_student_journey_stage", "pai_student_journeys", type_="check")
    op.create_check_constraint("ck_student_journey_stage", "pai_student_journeys",
                               _check((*LEGACY, *COUNSELOR)))
    op.create_index("uq_counselor_journey_active", "pai_student_journeys",
                    ["workspace_id"], unique=True,
                    postgresql_where=sa.text("journey_type = 'counselor_decision' AND status = 'active'"))
    connection = op.get_bind()
    for key, path, question, priority, tier, selector in QUESTIONS:
        connection.execute(sa.text("""
            INSERT INTO pai_profile_requirements
                (id, key, tier, source_type, source_key, source_path, selector,
                 applicability, question, priority, enabled, version)
            VALUES (:id, :key, :tier, 'record_field', 'goal', :path, :selector,
                    CAST(:applicability AS jsonb), :question, :priority, TRUE, 1)
            ON CONFLICT (key, version) DO NOTHING
        """), {"id": str(uuid5(NAMESPACE_URL, "pai-counselor-082:" + key)),
               "key": key, "tier": tier, "path": path, "selector": selector,
               "applicability": '{"record_exists:goal": true}',
               "question": question, "priority": priority})


def downgrade():
    connection = op.get_bind()
    for key, *_ in QUESTIONS:
        connection.execute(sa.text("DELETE FROM pai_profile_requirements WHERE id = :id"),
                           {"id": str(uuid5(NAMESPACE_URL, "pai-counselor-082:" + key))})
    op.drop_constraint("ck_profile_requirement_selector", "pai_profile_requirements", type_="check")
    op.create_check_constraint("ck_profile_requirement_selector", "pai_profile_requirements",
                               "selector IN ('any', 'current_or_highest')")
    op.drop_index("uq_counselor_journey_active", table_name="pai_student_journeys")
    op.drop_constraint("ck_student_journey_stage", "pai_student_journeys", type_="check")
    op.create_check_constraint("ck_student_journey_stage", "pai_student_journeys",
                               _check(LEGACY))
