# -*- coding: utf-8 -*-
"""The relevance version: one digest of the active Vault entries of the types
a caller names.

Path research (an explanation, a program search, an Operator result) is
current while the path-relevant part of the Vault it read is unchanged. The
digest covers the id and `updated_at` of every active fact, record and item of
those types, so any accepted write, correction or retraction to one gives a
new version. It lives in shared memory and takes the type list as an argument,
because memory never imports PAI C (FOUR_FEATURES_SPEC 2.3).
"""

import hashlib

from sqlalchemy import select

from app.memory.student_records import ENTITY_MODELS
from app.models import VaultFact, VaultItem


def relevance_version(db, workspace_id: str, types) -> str:
    """The digest over the active facts, records and items whose catalog type
    is in `types` only. Path research is current while this is unchanged, so
    a write that cannot change a path (a phone number, a city) leaves it
    current. The caller passes the list (PAI C policy data); memory never
    reads PAI C. 16 hex characters."""
    types = frozenset(types)

    def stamp(value) -> str:
        return value.isoformat() if value is not None else ""

    facts = select(VaultFact.id, VaultFact.updated_at).where(
        VaultFact.workspace_id == workspace_id, VaultFact.status == "active", VaultFact.field_key.in_(types))
    items = select(VaultItem.id, VaultItem.updated_at).where(
        VaultItem.workspace_id == workspace_id, VaultItem.status == "active", VaultItem.item_type.in_(types))
    rows = [f"fact:{id_}@{stamp(at)}" for id_, at in db.execute(facts)]
    rows += [f"item:{id_}@{stamp(at)}" for id_, at in db.execute(items)]
    for kind, model in ENTITY_MODELS.items():
        if kind not in types:
            continue
        rows += [f"{kind}:{id_}@{stamp(at)}" for id_, at in db.execute(select(model.id, model.updated_at).where(
            model.workspace_id == workspace_id, model.status == "active"))]
    return hashlib.sha256("|".join(sorted(rows)).encode()).hexdigest()[:16]
