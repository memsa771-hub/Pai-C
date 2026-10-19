"""Slice 2 tables: programme registry, page cache, research runs, agent runs; fact source and evidence.

Revision ID: os_0003
Revises: os_0002
Create Date: 2026-10-19

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0003"
down_revision = "os_0002"
branch_labels = None
depends_on = None

S = "os"
TS = sa.DateTime(timezone=True)
NOW = sa.func.now()
EMPTY_LIST = sa.text("'[]'::jsonb")
MONEY = sa.Numeric(12, 6)


def _id():
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", sa.Text, nullable=False)


def _in(column, values, name):
    return sa.CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=name)


def upgrade() -> None:
    op.create_table(
        "os_programmes", _id(), _tenant(),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column("route_key", sa.Text, nullable=False),
        sa.Column("university", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("aliases", JSONB, nullable=False, server_default=EMPTY_LIST),
        sa.Column("start_urls", JSONB, nullable=False, server_default=EMPTY_LIST),
        sa.Column("official_domains", JSONB, nullable=False, server_default=EMPTY_LIST),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("notes", sa.Text),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "ref", name="uq_os_programmes_ref"),
        _in("status", ("active", "excluded"), "ck_os_programmes_status"),
        schema=S,
    )
    op.create_table(
        "os_pages", _id(), _tenant(),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("final_url", sa.Text),
        sa.Column("http_status", sa.Integer),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("links", JSONB, nullable=False, server_default=EMPTY_LIST),
        sa.Column("blocked", sa.Text),
        sa.Column("fetched_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "url", name="uq_os_pages_url"),
        schema=S,
    )
    op.create_table(
        "os_research_runs", _id(), _tenant(),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("intake_year", sa.Integer, nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("started_at", TS, nullable=False, server_default=NOW),
        sa.Column("ended_at", TS),
        sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("confirmed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unconfirmed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", MONEY, nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "workflow_id", name="uq_os_research_runs_workflow"),
        _in("status", ("running", "done", "failed", "skipped_budget"), "ck_os_research_runs_status"),
        schema=S,
    )
    op.create_table(
        "os_agent_runs", _id(), _tenant(),
        sa.Column("research_run_id", sa.BigInteger,
                  sa.ForeignKey(f"{S}.os_research_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reading", sa.Text, nullable=False),
        sa.Column("agent", sa.Text, nullable=False),
        sa.Column("agent_version", sa.Integer, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cached_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", MONEY, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("research_run_id", "reading", name="uq_os_agent_runs_reading"),
        schema=S,
    )
    op.add_column("os_knowledge_facts", sa.Column("source", sa.Text, nullable=False, server_default="seed"), schema=S)
    op.add_column("os_knowledge_facts", sa.Column(
        "research_run_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_research_runs.id", ondelete="SET NULL")), schema=S)
    op.add_column("os_knowledge_facts", sa.Column("evidence", JSONB), schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_source", "os_knowledge_facts",
                               "source IN ('seed', 'manual', 'research')", schema=S)


def downgrade() -> None:
    op.drop_constraint("ck_os_knowledge_facts_source", "os_knowledge_facts", type_="check", schema=S)
    for column in ("evidence", "research_run_id", "source"):
        op.drop_column("os_knowledge_facts", column, schema=S)
    for name in ("os_agent_runs", "os_research_runs", "os_pages", "os_programmes"):
        op.drop_table(name, schema=S)
