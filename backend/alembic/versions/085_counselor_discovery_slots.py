"""Versioned Counselor discovery slots and shared pending turn answers.

Revision ID: 085
Revises: 084
"""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None

# Data for the registry, not executable conversation rules. Conditions are
# interpreted by CounselorSlotRegistry against the student's own state.
# key, stage, priority, source_type, source_key, source_path, selector,
# applicability, intent, accepts_unknown, English, Urdu, Roman Urdu.
SLOTS = (
    ("recent_qualification", "foundation", 100, "record_presence", "education", None, "any", {},
     "Find the most recent qualification studied or finished", False,
     "What are you studying now, or what did you finish most recently?",
     "آپ ابھی کیا پڑھ رہے ہیں، یا حال ہی میں کیا مکمل کیا؟",
     "Aap abhi kya parh rahe hain, ya haal hi mein kya mukammal kiya?"),
    ("qualification_group", "foundation", 90, "record_field", "education", "field_of_study", "current_or_highest", {},
     "Find the group or subjects in the recent qualification", True,
     "Which group or subjects did you study?", "آپ نے کون سا گروپ یا مضامین پڑھے؟",
     "Aap ne kaunsa group ya subjects parhe?"),
    ("academic_result", "foundation", 80, "record_field", "education", "result", "current_or_highest", {},
     "Find marks, grades or CGPA, without assuming a scale", True,
     "What marks, grades or CGPA did you receive?", "آپ کے نمبر، گریڈ یا سی جی پی اے کیا تھے؟",
     "Aap ke marks, grades ya CGPA kya thay?"),
    ("academic_status", "foundation", 70, "record_field", "education", "academic_status", "current_or_highest", {},
     "Find whether the recent qualification is current or finished", False,
     "Are you still studying it, or have you finished?", "کیا آپ ابھی یہ پڑھ رہے ہیں یا مکمل کر چکے ہیں؟",
     "Aap abhi yeh parh rahe hain ya mukammal kar chuke hain?"),
    ("subject_likes", "direction", 90, "record_field", "student_voice_statement", "statement", "any",
     {"slot_missing": "stated_goal"}, "Learn which subjects or activities the student enjoys or dislikes", True,
     "Which subjects or activities do you enjoy, and which do you dislike?",
     "آپ کو کون سے مضامین یا کام پسند اور ناپسند ہیں؟",
     "Aap ko kaun se subjects ya kaam pasand aur napasand hain?"),
    ("stated_goal", "direction", 100, "record_presence", "goal", None, "any", {},
     "Find the student's own education or career direction, if they have one", True,
     "What would you like to do next?", "آپ آگے کیا کرنا چاہتے ہیں؟",
     "Aap aage kya karna chahte hain?"),
    ("goal_reason", "direction", 95, "record_field", "goal", "details.motivation", "any",
     {"slot_value": "stated_goal"}, "Ask why the student wants this goal before suggesting routes", True,
     "What draws you to that direction?", "اس راستے میں آپ کی دلچسپی کیوں ہے؟",
     "Is raaste mein aap ki dilchaspi kyun hai?"),
    ("field_interest", "direction", 80, "vault_fact", "career.primary_interest", None, "any", {},
     "Find the field or interest the student wants to explore", True,
     "Which field or interest matters most to you?", "آپ کی سب سے زیادہ دلچسپی کس شعبے میں ہے؟",
     "Aap ki sab se zyada dilchaspi kis field mein hai?"),
    ("envisioned_outcome", "direction", 70, "record_field", "goal", "details.underlying_objective", "any", {},
     "Find what the student pictures doing after study or career change", True,
     "What do you picture doing after that?", "اس کے بعد آپ خود کو کیا کرتے دیکھتے ہیں؟",
     "Us ke baad aap khud ko kya karte dekhte hain?"),
    ("family_wish", "direction", 65, "record_field", "external_influence", "suggested_direction", "any",
     {"family_mentioned": True}, "Separate the family's preference from the student's own wish", True,
     "Is that your wish or your family's wish?", "کیا یہ آپ کی خواہش ہے یا گھر والوں کی؟",
     "Yeh aap ki khwahish hai ya ghar walon ki?"),
    ("budget", "direction", 60, "vault_fact", "finance.budget", None, "any", {},
     "Find an affordable budget and its period and currency", True,
     "Roughly how much can you spend on this?", "اس کے لیے آپ تقریباً کتنا خرچ کر سکتے ہیں؟",
     "Is ke liye aap taqreeban kitna kharch kar sakte hain?"),
    ("timing", "direction", 50, "record_field", "goal", "details.target_intake", "any", {},
     "Find when the student wants to start or change direction", True,
     "When would you like to start?", "آپ کب شروع کرنا چاہتے ہیں؟",
     "Aap kab shuru karna chahte hain?"),
    ("study_mode", "direction", 45, "vault_fact", "preferences.study_mode", None, "any",
     {"working_now": True}, "Find whether study must fit around current work", True,
     "Would you need to study part-time alongside work?", "کیا کام کے ساتھ جز وقتی پڑھنا ہوگا؟",
     "Kya kaam ke saath part-time parhna hoga?"),
    ("location_limits", "direction", 40, "vault_fact", "preferences.location_limits", None, "any", {},
     "Find where the student can or cannot study or work", True,
     "Are there places you need to stay in or avoid?", "کیا کسی جگہ رہنا یا کسی جگہ سے بچنا ضروری ہے؟",
     "Kya kisi jagah rehna ya kisi jagah se bachna zaroori hai?"),
    ("goal_summary_confirmed", "summary", 100, "journey_gap", "goal_summary_confirmed", None, "any", {},
     "Ask the student to confirm or correct their goal summary", False,
     "Is that right?", "کیا یہ درست ہے؟", "Kya yeh theek hai?"),
)


def upgrade():
    op.add_column("pai_profile_requirements", sa.Column("stage", sa.Text(), nullable=False,
                  server_default="profile"))
    op.add_column("pai_profile_requirements", sa.Column("question_intent", sa.Text()))
    op.add_column("pai_profile_requirements", sa.Column("canonical_questions", JSONB()))
    op.add_column("pai_profile_requirements", sa.Column("accepts_unknown", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")))
    op.create_check_constraint("ck_profile_requirement_stage", "pai_profile_requirements",
                               "stage IN ('profile', 'foundation', 'direction', 'summary')")
    op.create_index("idx_profile_requirements_stage", "pai_profile_requirements",
                    ["stage", "enabled", "priority"])
    op.create_table(
        "pai_counselor_slot_answers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("slot_key", sa.Text(), nullable=False),
        sa.Column("value", JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("confidence", sa.Float()),
        sa.Column("quote", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('pending', 'valid_unknown', 'declined')",
                           name="ck_counselor_slot_answer_status"),
        sa.UniqueConstraint("workspace_id", "source_event_id", "slot_key",
                            name="uq_counselor_slot_answer_event"),
    )
    op.create_index("idx_counselor_slot_answers_recent", "pai_counselor_slot_answers",
                    ["workspace_id", "created_at"])
    connection = op.get_bind()
    # A student may limit locations to cities or regions, not only countries.
    # Keep this as a normal Vault fact governed by the existing reconciler.
    connection.execute(sa.text("""
        INSERT INTO pai_vault_field_definitions
          (id, key, category, data_type, validation_schema, cardinality,
           conflict_policy, sensitivity, searchable, enabled, version,
           description, context_tags, required_for, profile_priority)
        VALUES (:id, 'preferences.location_limits', 'preferences', 'array',
                CAST(:schema AS jsonb), 'single', 'latest_wins', 'normal',
                TRUE, TRUE, 1, 'Places the student can or cannot study or work',
                CAST(:tags AS jsonb), CAST(:required_for AS jsonb), 65)
        ON CONFLICT (key, version) DO NOTHING
    """), {"id": str(uuid5(NAMESPACE_URL, "pai-counselor-085:preferences.location_limits")),
           "schema": json.dumps({"type": "array", "maxItems": 30,
                                 "items": {"type": "string", "minLength": 1, "maxLength": 200}}),
           "tags": json.dumps(["counseling", "matching"]),
           "required_for": json.dumps(["counseling"])})
    statement = sa.text("""
        INSERT INTO pai_profile_requirements
          (id, key, stage, tier, source_type, source_key, source_path, selector,
           applicability, question, question_intent, canonical_questions,
           accepts_unknown, priority, enabled, version)
        VALUES (:id, :key, :stage, :tier, :source_type, :source_key, :source_path,
                :selector, CAST(:applicability AS jsonb), :question, :intent,
                CAST(:canonical AS jsonb), :accepts_unknown, :priority, TRUE, 1)
        ON CONFLICT (key, version) DO NOTHING
    """)
    for key, stage, priority, source_type, source_key, path, selector, applicability, intent, unknown, en, ur, roman in SLOTS:
        connection.execute(statement, {
            "id": str(uuid5(NAMESPACE_URL, f"pai-counselor-085:{key}")),
            "key": f"discovery.{key}", "stage": stage, "tier": "important",
            "source_type": source_type, "source_key": source_key, "source_path": path,
            "selector": selector, "applicability": json.dumps(applicability),
            "question": en, "intent": intent,
            "canonical": json.dumps({"en": en, "ur": ur, "roman_ur": roman, "mixed": roman}, ensure_ascii=False),
            "accepts_unknown": unknown, "priority": priority,
        })


def downgrade():
    connection = op.get_bind()
    for key, *_ in SLOTS:
        connection.execute(sa.text("DELETE FROM pai_profile_requirements WHERE id = :id"),
                           {"id": str(uuid5(NAMESPACE_URL, f"pai-counselor-085:{key}"))})
    connection.execute(sa.text("DELETE FROM pai_vault_field_definitions WHERE id = :id"),
                       {"id": str(uuid5(NAMESPACE_URL, "pai-counselor-085:preferences.location_limits"))})
    op.drop_index("idx_counselor_slot_answers_recent", table_name="pai_counselor_slot_answers")
    op.drop_table("pai_counselor_slot_answers")
    op.drop_index("idx_profile_requirements_stage", table_name="pai_profile_requirements")
    op.drop_constraint("ck_profile_requirement_stage", "pai_profile_requirements", type_="check")
    op.drop_column("pai_profile_requirements", "accepts_unknown")
    op.drop_column("pai_profile_requirements", "canonical_questions")
    op.drop_column("pai_profile_requirements", "question_intent")
    op.drop_column("pai_profile_requirements", "stage")
