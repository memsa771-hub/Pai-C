"""Migration 116: item store, drop log and the ranged budget definition."""

import importlib.util
from pathlib import Path

import pytest

from app.database import Base
import app.models  # noqa: F401 — registers every table on Base.metadata
from app.memory.catalog import vault_catalog
from app.tools.schema import SchemaValidationError, validate_schema_instance

VERSIONS = Path(__file__).resolve().parents[1] / "alembic/versions"


def _load():
    spec = importlib.util.spec_from_file_location("vault_items_116", VERSIONS / "116_vault_items.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_116_revision_chain():
    migration = _load()
    assert (migration.revision, migration.down_revision) == ("116", "115")


def test_item_and_drop_tables_in_metadata():
    items, drops = Base.metadata.tables["pai_vault_items"], Base.metadata.tables["pai_vault_drops"]
    assert {"item_type", "type_version", "value", "level", "evidence", "status",
            "conflict_state", "superseded_by", "candidate_id"} <= set(items.c.keys())
    assert {"source", "stage", "reason", "payload", "source_ref"} <= set(drops.c.keys())
    assert {c.name for c in items.constraints if c.name} >= {
        "ck_vault_item_level", "ck_vault_item_status", "ck_vault_item_conflict_state"}
    assert {c.name for c in drops.constraints if c.name} >= {
        "ck_vault_drop_source", "ck_vault_drop_stage"}


def test_budget_definition_v2_schema():
    schema = _load().BUDGET_SCHEMA
    validate_schema_instance(schema, {"band": "1_3_lakh", "covers": "fees_and_living"})
    validate_schema_instance(schema, {"amount": 500000, "currency": "PKR", "period": "per_year"})
    for bad in ({"band": "rich"}, {"covers": "everything"}, {"min": -1}, {"extra": 1},
                {"period": "weekly"}, {"approximate": "yes"}):
        with pytest.raises(SchemaValidationError):
            validate_schema_instance(schema, bad)


def test_budget_literals_match_the_catalog():
    props = _load().BUDGET_SCHEMA["properties"]
    assert props["band"]["enum"] == [c.code for c in vault_catalog().choices("budget_bands")]
    assert props["covers"]["enum"] == [c.code for c in vault_catalog().choices("budget_covers")]
