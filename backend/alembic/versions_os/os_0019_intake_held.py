"""P1-T3 Task 1: the Counsellor intake gains the statuses `held` (a decision whose consent is missing and that has no
plan yet) and `paused` (a decision whose consent is missing, so its existing plan was paused) (R-10, P1-D11). The reason check gains `consent_missing`.

Revision ID: os_0019
Revises: os_0018
Create Date: 2026-11-05

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

from alembic import op

revision = "os_0019"
down_revision = "os_0018"
branch_labels = None
depends_on = None

S = "os"
T = "os_counsellor_intake"
CK = "ck_os_counsellor_intake_status"
OLD = ("pending", "planned", "revised", "replaced", "refused", "stale", "withdrawn", "unsupported")
NEW = (*OLD, "held", "paused")
CK_REASON = "ck_os_counsellor_intake_reason"
REASONS_OLD = ("not_authorized", "invalid_export", "route_not_supported", "unknown_programme", "self_serve_plan_open",
               "plan_closed")
REASONS_NEW = (*REASONS_OLD, "consent_missing")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint(CK, T, schema=S, type_="check")
    op.create_check_constraint(CK, T, _in("status", NEW), schema=S)
    op.drop_constraint(CK_REASON, T, schema=S, type_="check")
    op.create_check_constraint(CK_REASON, T, _in("reason", REASONS_NEW), schema=S)


def downgrade() -> None:
    op.execute(f"UPDATE {S}.{T} SET status = 'refused', reason = NULL WHERE status IN ('held', 'paused')")
    op.drop_constraint(CK_REASON, T, schema=S, type_="check")
    op.create_check_constraint(CK_REASON, T, _in("reason", REASONS_OLD), schema=S)
    op.drop_constraint(CK, T, schema=S, type_="check")
    op.create_check_constraint(CK, T, _in("status", OLD), schema=S)
