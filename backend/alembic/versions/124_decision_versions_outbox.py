"""Decision versions and the OS outbox (P1-T2, R-79).

Revision ID: 124
Revises: 123

Every route decision gets a `decision_version` (1, 2, 3 ... per workspace) and
the fields PAI OS reads (status, countries, level, places, intake, OS support,
authorisation). The `withdrawn_at` marker and the partial index
`uq_route_decision_active` (one active row per workspace) stay as they are
(rule D-a); a withdrawal is now also a version row of its own, inserted with
`withdrawn_at = chosen_at`, so it is never "active". New table
`pai_os_outbox` holds what is waiting to be delivered to PAI OS.

Backfill, per workspace in (chosen_at, id) order: each existing row takes the
next version; a row that was really withdrawn is followed by a `withdrawn`
version row (a copy of it, stamped at its withdrawal time, with no steps
done). A row whose `withdrawn_at` equals the next row's `chosen_at` was a
change of route (the old `choose()` stamped the previous row with the same
time), not a withdrawal: it gets no withdrawn row, as the live code writes a
change. Downgrade deletes those withdrawn version rows and drops everything
this migration added.
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "124"
down_revision = "123"
branch_labels = depends_on = None

TABLE = "pai_route_decisions"
OUTBOX = "pai_os_outbox"
VERSION_INDEX = "uq_route_decision_version"

COPY_AS_WITHDRAWN = (
    "INSERT INTO pai_route_decisions (id, workspace_id, field_key, possibility_id, title, verdict, route, "
    "steps, steps_done, chosen_at, withdrawn_at, decision_version, status, places, os_supported, "
    "guardian_required) "
    "SELECT :new_id, workspace_id, field_key, possibility_id, title, verdict, route, steps, steps_done, "
    "withdrawn_at, withdrawn_at, :version, 'withdrawn', places, os_supported, guardian_required "
    "FROM pai_route_decisions WHERE id = :id")
# A withdrawal has no steps done, like the live `withdraw()`. A separate UPDATE so the literal takes the column's
# type on every dialect (an untyped literal in INSERT ... SELECT is text on Postgres).
NO_STEPS_DONE = "UPDATE pai_route_decisions SET steps_done = '[]' WHERE id = :id"


def _backfill(bind):
    rows = bind.execute(sa.text(
        "SELECT id, workspace_id, chosen_at, withdrawn_at FROM pai_route_decisions "
        "ORDER BY workspace_id, chosen_at, id")).fetchall()
    versions: dict = {}
    for index, (ident, workspace, _chosen_at, withdrawn_at) in enumerate(rows):
        version = versions.get(workspace, 0) + 1
        bind.execute(sa.text("UPDATE pai_route_decisions SET decision_version = :v WHERE id = :id"),
                     {"v": version, "id": ident})
        following = rows[index + 1] if index + 1 < len(rows) else None
        changed = following is not None and following[1] == workspace and following[2] == withdrawn_at
        if withdrawn_at is not None and not changed:
            version += 1
            new_id = str(uuid.uuid4())
            bind.execute(sa.text(COPY_AS_WITHDRAWN), {"new_id": new_id, "version": version, "id": ident})
            bind.execute(sa.text(NO_STEPS_DONE), {"id": new_id})
        versions[workspace] = version


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("decision_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'chosen'")))
        for name in ("origin_country", "destination_country", "level", "path_ref"):
            batch.add_column(sa.Column(name, sa.Text(), nullable=True))
        batch.add_column(sa.Column("places", JSONB(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("intake", JSONB(), nullable=True))
        batch.add_column(sa.Column("os_supported", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("guardian_authorized_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("guardian_required", sa.Boolean(), nullable=False,
                                   server_default=sa.text("false")))
    _backfill(op.get_bind())
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("decision_version", existing_type=sa.Integer(), nullable=False)
        batch.create_index(VERSION_INDEX, ["workspace_id", "decision_version"], unique=True)

    op.create_table(
        OUTBOX,
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_os_outbox_status_created", OUTBOX, ["status", "created_at"])


def downgrade():
    op.drop_index("idx_os_outbox_status_created", table_name=OUTBOX)
    op.drop_table(OUTBOX)
    op.execute("DELETE FROM pai_route_decisions WHERE status = 'withdrawn'")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_index(VERSION_INDEX)
        for name in ("guardian_required", "guardian_authorized_at", "authorized_at", "os_supported", "intake",
                     "places", "path_ref", "level", "destination_country", "origin_country", "status",
                     "decision_version"):
            batch.drop_column(name)
