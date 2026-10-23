"""This repo is PAI C only: drop the PAI OS tables it no longer has code for.

Revision ID: 115
Revises: 114

PAI OS hands work to and from PAI C only through the decision record,
student requests and escalations. The tables below belonged to OS features
removed from this app: shared browser tabs, to-dos, timers, routines,
chat-platform integrations, model credentials, invitations, the application
workspace and deadlines, plus the retired `pai_sessions` and
`auth_identities`. Their data is deleted.

Children are dropped before their parents, without CASCADE, so an unexpected
dependency fails the migration instead of silently dropping a constraint.
Back up first (scripts/backup-postgres.sh): the downgrade cannot restore data.
"""
from alembic import op

revision = "115"
down_revision = "114"
branch_labels = depends_on = None

TABLES = (
    "pai_application_routines", "pai_application_requirements", "pai_application_plans",
    "pai_saved_institutions", "pai_student_deadlines", "pai_deadline_settings",
    "routines", "timers", "todos", "integration_bindings",
    "browser_tabs", "browser_usage", "browser_contexts",
    "model_access", "invitations", "pai_sessions", "auth_identities",
)


def upgrade():
    for table in TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}"')


def downgrade():
    raise RuntimeError("115 dropped tables and their data; restore from a backup instead")
