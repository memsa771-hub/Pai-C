"""Lossless World and capability storage, including every history version.

Revision ID: 107
Revises: 106
"""
from alembic import op
import sqlalchemy as sa
from app.pai_c.deep.migrate_v2 import migrate_v2

revision = "107"
down_revision = "106"
branch_labels = depends_on = None


def _convert(upgrading):
    bind = op.get_bind()
    for name in ("counselor_notebooks", "counselor_notebook_history"):
        table = sa.Table(name, sa.MetaData(), autoload_with=bind)
        for row in bind.execute(sa.select(table)).mappings().all():
            original = row["notebook"]
            if upgrading:
                data = migrate_v2(original)
            elif original.get("legacy_v2") is not None:
                data = original["legacy_v2"]
            else:
                raise ValueError("Cannot downgrade a new v3 notebook without a v2 archive")
            bind.execute(table.update().where(table.c.id == row["id"]).values(notebook=data))


def upgrade():
    _convert(True)


def downgrade():
    _convert(False)
