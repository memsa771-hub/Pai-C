# -*- coding: utf-8 -*-
"""The Vault version: one digest of every active Vault entry.

Research that reads the student (a path explanation, a program search, an
Operator result) is current for the Vault it was run on. The digest covers the
id and `updated_at` of every active fact, record and item, so any accepted
write, correction or retraction gives a new version (FOUR_FEATURES_SPEC 2.3).
It lives in shared memory because PAI C, research and Operator all read it and
memory never imports PAI C.
"""

import hashlib

from sqlalchemy import select

from app.memory.student_records import ENTITY_MODELS
from app.models import VaultFact, VaultItem


def vault_version(db, workspace_id: str) -> str:
    """16 hex characters; the same Vault always gives the same version."""
    def stamp(value) -> str:
        return value.isoformat() if value is not None else ""

    rows = [f"fact:{id_}@{stamp(at)}" for id_, at in db.execute(select(VaultFact.id, VaultFact.updated_at).where(
        VaultFact.workspace_id == workspace_id, VaultFact.status == "active"))]
    rows += [f"item:{id_}@{stamp(at)}" for id_, at in db.execute(select(VaultItem.id, VaultItem.updated_at).where(
        VaultItem.workspace_id == workspace_id, VaultItem.status == "active"))]
    for kind, model in ENTITY_MODELS.items():
        rows += [f"{kind}:{id_}@{stamp(at)}" for id_, at in db.execute(select(model.id, model.updated_at).where(
            model.workspace_id == workspace_id, model.status == "active"))]
    return hashlib.sha256("|".join(sorted(rows)).encode()).hexdigest()[:16]
