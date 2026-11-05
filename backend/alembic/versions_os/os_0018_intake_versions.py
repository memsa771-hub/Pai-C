"""P1-T2 Task 4: the Counsellor intake keeps each decision version and its status (R-02, R-06).

New columns `decision_version` and `decision_status` (null for v1 rows; no check on the status, so an invalid export
still gets stored and the worker refuses it with a reason); the intake status gains `stale` (an older
version than one already processed) and `withdrawn` (the plan was closed because the student withdrew the decision).

Revision ID: os_0018
Revises: os_0017
Create Date: 2026-11-04

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0018"
down_revision = "os_0017"
branch_labels = None
depends_on = None

S = "os"
T = "os_counsellor_intake"
CK = "ck_os_counsellor_intake_status"
OLD = ("pending", "planned", "revised", "replaced", "refused")
NEW = (*OLD, "stale", "withdrawn")
IX = "ix_os_counsellor_intake_version"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column(T, sa.Column("decision_version", sa.Integer), schema=S)
    op.add_column(T, sa.Column("decision_status", sa.Text), schema=S)
    op.drop_constraint(CK, T, schema=S, type_="check")
    op.create_check_constraint(CK, T, _in("status", NEW), schema=S)
    op.create_index(IX, T, ["tenant_id", "student_ref", "decision_version"], schema=S)


def downgrade() -> None:
    op.drop_index(IX, table_name=T, schema=S)
    op.execute(f"UPDATE {S}.{T} SET status = 'refused', reason = NULL WHERE status IN ('stale', 'withdrawn')")
    op.drop_constraint(CK, T, schema=S, type_="check")
    op.create_check_constraint(CK, T, _in("status", OLD), schema=S)
    op.drop_column(T, "decision_status", schema=S)
    op.drop_column(T, "decision_version", schema=S)
