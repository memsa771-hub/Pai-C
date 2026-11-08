"""P2-T2: the registry (P2 spec §4.1, P2-D2, P2-D3, P2-D4; R-32, R-33, R-34): `os_registry` with its append-only
revisions and links, the programme level on `os_programmes`, and the `registry` fact scope.

Revision ID: os_0026
Revises: os_0025
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "os_0026"
down_revision = "os_0025"
branch_labels = None
depends_on = None

S = "os"
KINDS = ("regulator", "board", "admission_body", "admission_system", "entry_test", "institution", "campus",
         "seat_category", "calendar", "official_list")
STATUSES = ("active", "closed", "merged", "renamed")
CAUSES = ("seed", "manual", "research", "import", "review", "monitor", "report", "rollover")
REVISION_KINDS = ("entity", "link", "programme")
PROGRAMME_COLUMNS = ("institution_id", "campus_id", "level", "field", "family", "region")


def _in(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=name)


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def upgrade() -> None:
    op.drop_constraint("ck_os_knowledge_facts_scope", "os_knowledge_facts", schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_scope", "os_knowledge_facts",
                               "scope IN ('route', 'programme', 'registry')", schema=S)
    for col in PROGRAMME_COLUMNS:
        op.add_column("os_programmes", sa.Column(col, sa.Text), schema=S)
    op.create_index("ix_os_programmes_institution", "os_programmes", ["tenant_id", "institution_id"], schema=S)
    op.create_table(
        "os_registry", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("parent_id", sa.Text),
        sa.Column("region", sa.Text),
        sa.Column("institution_type", sa.Text),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("aliases", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("official_domains", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("successor_id", sa.Text),
        sa.Column("list_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("quote", sa.Text, nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attrs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "entity_id", name="uq_os_registry_entity"),
        _in("kind", KINDS, "ck_os_registry_kind"),
        _in("status", STATUSES, "ck_os_registry_status"),
        schema=S,
    )
    op.create_index("ix_os_registry_kind_region", "os_registry", ["tenant_id", "kind", "region"], schema=S)
    op.create_index("ix_os_registry_parent", "os_registry", ["tenant_id", "parent_id"], schema=S)
    op.create_table(
        "os_registry_revisions", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("registry_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_registry.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("kind", sa.Text, nullable=False, server_default="entity"),
        sa.Column("subject", sa.Text),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB, nullable=False),
        sa.Column("cause", sa.Text, nullable=False),
        sa.Column("cause_ref", sa.Text),
        sa.Column("actor", sa.Text),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _in("kind", REVISION_KINDS, "ck_os_registry_revisions_kind"),
        _in("action", ("insert", "change", "status", "undo"), "ck_os_registry_revisions_action"),
        _in("cause", CAUSES, "ck_os_registry_revisions_cause"),
        schema=S,
    )
    op.create_index("ix_os_registry_revisions_entity", "os_registry_revisions", ["tenant_id", "registry_id", "id"],
                    schema=S)
    op.create_table(
        "os_registry_links", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("from_id", sa.Text, nullable=False),
        sa.Column("rel", sa.Text, nullable=False),
        sa.Column("to_kind", sa.Text, nullable=False),
        sa.Column("to_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "from_id", "rel", "to_kind", "to_id", name="uq_os_registry_links"),
        _in("rel", ("uses_test", "has_category", "admits"), "ck_os_registry_links_rel"),
        _in("to_kind", ("registry", "programme"), "ck_os_registry_links_to_kind"),
        schema=S,
    )
    op.create_index("ix_os_registry_links_to", "os_registry_links", ["tenant_id", "to_kind", "to_id"], schema=S)


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("os_registry", "os_registry_links"):
        if conn.execute(sa.text(f"SELECT 1 FROM {S}.{table} LIMIT 1")).first():
            raise RuntimeError(f"os_0026 downgrade refused: {table} holds rows (no silent loss)")
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.os_knowledge_facts WHERE scope = 'registry' LIMIT 1")).first():
        raise RuntimeError("os_0026 downgrade refused: facts of scope 'registry' exist (no silent loss)")
    linked = " OR ".join(f"{c} IS NOT NULL" for c in PROGRAMME_COLUMNS)
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.os_programmes WHERE {linked} LIMIT 1")).first():
        raise RuntimeError("os_0026 downgrade refused: programmes carry registry columns (no silent loss)")
    op.drop_table("os_registry_links", schema=S)
    op.drop_table("os_registry_revisions", schema=S)
    op.drop_table("os_registry", schema=S)
    op.drop_index("ix_os_programmes_institution", "os_programmes", schema=S)
    for col in reversed(PROGRAMME_COLUMNS):
        op.drop_column("os_programmes", col, schema=S)
    op.drop_constraint("ck_os_knowledge_facts_scope", "os_knowledge_facts", schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_scope", "os_knowledge_facts",
                               "scope IN ('route', 'programme')", schema=S)
