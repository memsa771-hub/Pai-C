"""Slice 6a: the application pack is an artifact (spec S6a-D7): kind `pack`, the statuses `building`, `ready` and
`incomplete`, and versions written by the system (the manifest), not by the Writer or the student.

Revision ID: os_0010
Revises: os_0009
Create Date: 2026-10-22

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

from alembic import op

revision = "os_0010"
down_revision = "os_0009"
branch_labels = None
depends_on = None

S = "os"
KINDS_OLD, KINDS_NEW = ("sop", "cv"), ("sop", "cv", "pack")
STATUS_OLD = ("empty", "drafting", "draft", "needs_answers", "failed", "budget", "approved")
STATUS_NEW = STATUS_OLD + ("building", "ready", "incomplete")
AUTHOR_OLD, AUTHOR_NEW = ("writer", "student"), ("writer", "student", "system")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _swap(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(name, table, type_="check", schema=S)
    op.create_check_constraint(name, table, _in(column, values), schema=S)


def upgrade() -> None:
    _swap("os_artifacts", "ck_os_artifacts_kind", "kind", KINDS_NEW)
    _swap("os_artifacts", "ck_os_artifacts_status", "status", STATUS_NEW)
    _swap("os_artifact_versions", "ck_os_artifact_versions_author", "author", AUTHOR_NEW)


def downgrade() -> None:
    op.execute(f"DELETE FROM {S}.os_artifacts WHERE kind = 'pack'")
    _swap("os_artifacts", "ck_os_artifacts_kind", "kind", KINDS_OLD)
    _swap("os_artifacts", "ck_os_artifacts_status", "status", STATUS_OLD)
    _swap("os_artifact_versions", "ck_os_artifact_versions_author", "author", AUTHOR_OLD)
