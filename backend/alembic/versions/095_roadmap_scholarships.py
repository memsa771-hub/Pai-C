"""Keep cited scholarship leads with their roadmap, separate from profile facts.

Revision ID: 095
Revises: 094
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pai_roadmaps", sa.Column("scholarships", JSONB(), nullable=False,
                                          server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column("pai_roadmaps", "scholarships")
