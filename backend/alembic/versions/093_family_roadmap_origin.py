"""Allow a family wish to remain separate from the student's own direction.

Revision ID: 093
Revises: 092
"""

from alembic import op

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_roadmap_origin", "pai_roadmaps", type_="check")
    op.create_check_constraint("ck_roadmap_origin", "pai_roadmaps",
                               "origin IN ('stated_goal', 'alternative', 'family_wish', 'student_added', 'operator_suggested')")


def downgrade():
    op.execute("UPDATE pai_roadmaps SET origin = 'alternative' WHERE origin = 'family_wish'")
    op.drop_constraint("ck_roadmap_origin", "pai_roadmaps", type_="check")
    op.create_check_constraint("ck_roadmap_origin", "pai_roadmaps",
                               "origin IN ('stated_goal', 'alternative', 'student_added', 'operator_suggested')")
