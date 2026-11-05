"""Migration 125: the guardian consent table and the agreed consent text version on a decision (R-10)."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.database import Base
import app.models  # noqa: F401 - registers every table on Base.metadata

pytestmark = pytest.mark.req("R-10")

BACKEND = Path(__file__).resolve().parents[1]
TABLE = "pai_guardian_consents"
COLUMNS = {"id", "workspace_id", "decision_id", "decision_version", "purpose", "email", "token_hash", "expires_at",
           "used_at", "text_version", "outcome", "created_at"}


def _load():
    spec = importlib.util.spec_from_file_location("migration125", BACKEND / "alembic/versions/125_guardian_consents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _database_at_124():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE workspaces (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE pai_route_decisions (id TEXT PRIMARY KEY)"))
    return engine


def _migrate(connection, fn):
    migration = _load()
    with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
        getattr(migration, fn)()


def test_125_chains_after_124_and_matches_the_model():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("125", "124")
    table = Base.metadata.tables[TABLE]
    assert set(table.columns.keys()) == COLUMNS
    assert table.c.token_hash.unique and not table.c.token_hash.nullable
    assert table.c.decision_id.nullable and table.c.used_at.nullable
    assert {fk.ondelete for fk in table.c.workspace_id.foreign_keys} == {"CASCADE"}
    assert {fk.ondelete for fk in table.c.decision_id.foreign_keys} == {"SET NULL"}
    decisions = Base.metadata.tables["pai_route_decisions"]
    assert "consent_version" in decisions.columns and decisions.c.consent_version.nullable


def test_125_upgrade_and_downgrade():
    engine = _database_at_124()
    with engine.begin() as connection:
        _migrate(connection, "upgrade")
        inspector = inspect(connection)
        assert TABLE in inspector.get_table_names()
        assert COLUMNS == {c["name"] for c in inspector.get_columns(TABLE)}
        decision_columns = {c["name"]: c for c in inspector.get_columns("pai_route_decisions")}
        assert decision_columns["consent_version"]["nullable"]
        connection.execute(text("INSERT INTO workspaces VALUES ('w')"))
        insert = ("INSERT INTO pai_guardian_consents (id, workspace_id, decision_version, email, token_hash, "
                  "expires_at, text_version, outcome) VALUES ('a', 'w', 1, 'g@x.org', :h, CURRENT_TIMESTAMP, '1', 'sent')")
        connection.execute(text(insert), {"h": "hash"})
        with pytest.raises(Exception):  # token_hash is unique
            connection.execute(text(insert.replace("'a'", "'b'")), {"h": "hash"})
    with engine.begin() as connection:
        _migrate(connection, "downgrade")
        assert TABLE not in inspect(connection).get_table_names()
        assert "consent_version" not in {c["name"] for c in inspect(connection).get_columns("pai_route_decisions")}


def test_125_check_constraints():
    engine = _database_at_124()
    with engine.begin() as connection:
        _migrate(connection, "upgrade")
        connection.execute(text("INSERT INTO workspaces VALUES ('w')"))
        insert = ("INSERT INTO pai_guardian_consents (id, workspace_id, decision_version, email, token_hash, "
                  "text_version, {cols}) VALUES ('{i}', 'w', 1, 'g@x.org', '{i}', '1', {vals})")
        connection.execute(text(insert.format(cols="purpose, outcome", i="ok", vals="'withdraw', 'stale'")))
        # an agree link always has an end; a withdraw link may have none
        for cols, vals in (("purpose, outcome", "'other', 'sent'"), ("purpose, outcome", "'agree', 'used'"),
                           ("purpose, outcome", "'agree', 'sent'")):
            with pytest.raises(Exception):
                with connection.begin_nested():
                    connection.execute(text(insert.format(cols=cols, i="bad", vals=vals)))
    table = Base.metadata.tables[TABLE]
    assert {c.name for c in table.constraints if c.name} >= {"ck_guardian_consent_purpose",
                                                              "ck_guardian_consent_outcome",
                                                              "ck_guardian_consent_agree_expires"}
    assert table.c.expires_at.nullable  # a withdraw link has no fixed end
