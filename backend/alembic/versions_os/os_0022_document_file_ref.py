"""P1-T7 Task 1: `os_documents.file_ref` links an OS document to the Counsellor file that holds its bytes (R-01,
P1-D2, D-y1). A row with a `file_ref` has no `os_document_files` row: the bytes live in the Counsellor file store and
are read through the DocumentFiles port. One live document per tenant and file.

Revision ID: os_0022
Revises: os_0021
Create Date: 2026-11-06

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0022"
down_revision = "os_0021"
branch_labels = None
depends_on = None

S = "os"
T = "os_documents"
INDEX = "uq_os_documents_file_ref"


def upgrade() -> None:
    op.add_column(T, sa.Column("file_ref", sa.Text, nullable=True), schema=S)
    op.create_index(INDEX, T, ["tenant_id", "file_ref"], unique=True, schema=S,
                    postgresql_where=sa.text("file_ref IS NOT NULL AND status <> 'deleted'"))


def downgrade() -> None:
    # A linked document has no bytes here: dropping the column would leave a row nobody can read.
    left = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM os.os_documents d WHERE d.file_ref IS NOT NULL AND d.status <> 'deleted' "
        "AND NOT EXISTS (SELECT 1 FROM os.os_document_files f WHERE f.document_id = d.id)")).scalar()
    if left:
        raise RuntimeError("cannot downgrade os_0022: live documents with a file_ref have no bytes in the OS")
    op.drop_index(INDEX, table_name=T, schema=S)
    op.drop_column(T, "file_ref", schema=S)
