# -*- coding: utf-8 -*-
"""Vault field definitions — the Vault's schema, stored as data.

Adding a new field must be an INSERT, never an edit to reconciliation or
retrieval. So every rule that varies per field lives in a row:

    validation_schema   what a legal value looks like (JSON Schema fragment)
    cardinality         single (one active fact) | multi (a set)
    conflict_policy     how a new value resolves against an existing one
    sensitivity         whether it may go into prompt context freely

Production's rows are data inserted by migrations, and nothing in this package
branches on any of these keys. The Vault catalog keeps the same definitions
(`catalog_field_definitions`) for isolated test and eval students.
"""

import logging
from typing import Any, Optional

from sqlalchemy import select

from app.models import VaultFieldDefinition
from app.tools.executor import _validate

from .errors import MemoryDataError

logger = logging.getLogger(__name__)

FIELD_ALIASES = {"preferences.countries": "preferences.target_countries"}


class VaultFieldError(MemoryDataError):
    """A proposed value does not satisfy its field definition."""


def usable_in_counseling(definition) -> bool:
    """Restricted identifiers never enter routine conversation prompts."""
    return definition is not None and (
        definition.sensitivity == "normal" or
        (definition.sensitivity == "sensitive" and
         "counseling" in (definition.context_tags or []))
    )


def catalog_field_definitions() -> list[dict]:
    """Upsert specs for every catalog fact: the definitions production's
    migrations seed, kept as data in the Vault catalog. Isolated students in
    tests and evals are seeded from this, so they validate like production."""
    from copy import deepcopy
    from .catalog import vault_catalog
    return [{"key": spec.key, "sensitivity": spec.sensitivity, **deepcopy(spec.field_definition)}
            for spec in vault_catalog().types("fact") if spec.field_definition]


class VaultFieldDefinitionService:
    """Reads and validates against the field-definition table."""

    def __init__(self, db):
        self.db = db

    def get(self, key: str) -> Optional[VaultFieldDefinition]:
        """The highest enabled version of a field definition."""
        return self.db.execute(
            select(VaultFieldDefinition)
            .where(
                VaultFieldDefinition.key == key,
                VaultFieldDefinition.enabled.is_(True),
            )
            .order_by(VaultFieldDefinition.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def list_definitions(self, category: Optional[str] = None) -> list[VaultFieldDefinition]:
        stmt = select(VaultFieldDefinition).where(
            VaultFieldDefinition.enabled.is_(True)
        )
        if category:
            stmt = stmt.where(VaultFieldDefinition.category == category)
        return list(self.db.execute(stmt.order_by(VaultFieldDefinition.key)).scalars().all())

    def keys(self) -> tuple[str, ...]:
        return tuple(d.key for d in self.list_definitions())

    def validate(self, key: str, value: Any) -> VaultFieldDefinition:
        """Check `value` against `key`'s definition. Raises VaultFieldError.

        Reuses the tool runtime's `_validate` rather than adding a second
        JSON-Schema implementation — one validator, one set of bugs, and a
        Vault field schema behaves exactly like a tool argument schema.
        """
        definition = self.get(key)
        if definition is None:
            raise VaultFieldError(f"no enabled field definition for {key}")

        schema = definition.validation_schema
        if schema:
            try:
                _validate(schema, value, path=key)
            except ValueError as exc:
                raise VaultFieldError(str(exc)) from exc
        return definition

    def upsert_definition(self, spec: dict) -> VaultFieldDefinition:
        """Create a definition, or supersede it with a new version.

        Versioning rather than mutation: an existing fact stays interpretable
        against the definition it was accepted under.
        """
        existing = self.get(spec["key"])
        version = 1 if existing is None else (existing.version or 1) + 1
        if existing is not None:
            existing.enabled = False

        definition = VaultFieldDefinition(
            key=spec["key"],
            category=spec.get("category", "general"),
            data_type=spec.get("data_type", "string"),
            validation_schema=spec.get("validation_schema"),
            cardinality=spec.get("cardinality", "single"),
            conflict_policy=spec.get("conflict_policy", "latest_wins"),
            sensitivity=spec.get("sensitivity", "normal"),
            searchable=bool(spec.get("searchable", False)),
            context_tags=spec.get("context_tags"),
            required_for=spec.get("required_for"),
            profile_priority=spec.get("profile_priority", 50),
            extractable_from=spec.get("extractable_from"),
            verification_policy=spec.get("verification_policy"),
            source_policy=spec.get("source_policy", existing.source_policy if existing else None),
            enabled=True,
            version=version,
            description=spec.get("description"),
        )
        self.db.add(definition)
        self.db.flush()
        return definition
