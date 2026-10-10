"""Lossless Truth Map v2, including immutable original v1 JSON.

Revision ID: 101
Revises: 100
"""
from alembic import op
import sqlalchemy as sa
from app.pai_c.deep.migrate_v1 import migrate_v1

revision = "101"
down_revision = "100"
branch_labels = depends_on = None


def _convert(upgrade):
    bind = op.get_bind()
    for name in ("counselor_notebooks", "counselor_notebook_history"):
        table = sa.Table(name, sa.MetaData(), autoload_with=bind)
        for row in bind.execute(sa.select(table)).mappings().all():
            data = row["notebook"]
            if upgrade:
                first = row.get("created_at")
                if first is None:
                    history = sa.Table("counselor_notebook_history", sa.MetaData(), autoload_with=bind)
                    first = bind.scalar(sa.select(sa.func.min(history.c.created_at)).where(history.c.workspace_id == row["workspace_id"])) or row["updated_at"]
                data = migrate_v1(data, first, row.get("updated_at"))
            elif data.get("legacy_v1") is not None:
                data = data["legacy_v1"]
            else:
                raise ValueError("Cannot downgrade a new v2 notebook without a v1 archive")
            bind.execute(table.update().where(table.c.id == row["id"]).values(notebook=data))


def upgrade():
    _convert(True)


def downgrade():
    _convert(False)
