"""The per-student Vault version and the Vault events (P1-T4, R-13, P1-D15).

`after_accept(db, candidate)` is a reconciler accept hook. Every accepted Vault write that touches a StudentFacts key
bumps the student's version in the writer's transaction (so a write and its version commit or roll back together) and,
when the part is on, queues a `vault_event` outbox row for PAI OS. The counter reads the raw
`config.CONNECT_STUDENT_FACTS`, never `part_on`, so a Vault write never queries the OS engine; with the flag off there
is no version row and no outbox row. A failed bump is never swallowed: a lost version would be a missed replan.

`keys_for(candidate)` is the single map from a candidate to StudentFacts keys. Its words live in
`student_facts_keys.yaml`.
"""

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select

from app.config import config
from app.models import VaultVersion, Workspace
from app.pai_c.connect import outbox

log = logging.getLogger("app.pai_c.connect.vault_version")
_KEYS = Path(__file__).with_name("student_facts_keys.yaml")


@lru_cache(maxsize=1)
def _map() -> dict:
    return yaml.safe_load(_KEYS.read_text(encoding="utf-8"))


def _unwrap(value):
    if isinstance(value, dict) and set(value) == {"value"}:
        return value["value"]
    return value


_FIELD = {"education": ("qualification_name", "EducationRecord"), "test_attempt": ("test_type", "TestAttempt")}


def _record_values(db, candidate) -> dict:
    """What the candidate says about the record, with the level (or test type) filled in from the stored record when
    the candidate patches or retracts one and does not carry it. A retracted record is read too."""
    proposed = _unwrap(candidate.proposed_value)
    values = dict(proposed) if isinstance(proposed, dict) else {}
    field, model_name = _FIELD[candidate.key]
    record_id = (candidate.entities or {}).get("record_id")
    if db is not None and record_id and not values.get(field):
        try:
            from app import models

            row = db.get(getattr(models, model_name), record_id)
            if row is not None and str(row.workspace_id) == str(candidate.workspace_id):
                values[field] = getattr(row, field)
        except Exception:  # noqa: BLE001  (an unreadable record gives no keys)
            log.warning("vault_version_record_unreadable")
    return values


def _education_keys(values: dict) -> list[str]:
    from app.pai_c.memory import vault_catalog

    catalog = vault_catalog()
    level = catalog.record_level(catalog.type("education"), values)
    for family, codes in _map()["education"]["families"].items():
        if level in codes:
            return [f"education.{family}.{field}" for field in _map()["education"]["fields"]]
    return []


def _test_keys(values: dict) -> list[str]:
    from app.pai_c.memory import vault_catalog

    text = str(values.get("test_type") or "").strip()
    if not text:
        return []
    code = vault_catalog().choice_code("tests", text) or re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")
    return [_map()["tests"]["key"].format(type=code)] if code else []


def keys_for(candidate, db=None) -> list[str]:
    """The StudentFacts keys the candidate touches (sorted, no repeats); empty for a candidate that touches none.
    `db` is optional: with it a patch or a retract of a record that does not carry its own level or test type
    reads it from the stored record."""
    kind, key = candidate.candidate_type, candidate.key
    mapping = _map()
    if kind == "vault_fact":
        found = mapping["facts"].get(key, [])
    elif kind == "vault_item":
        found = mapping["items"].get(key, [])
    elif kind == "student_record" and key == "education":
        found = _education_keys(_record_values(db, candidate))
    elif kind == "student_record" and key == mapping["tests"]["record"]:
        found = _test_keys(_record_values(db, candidate))
    else:
        found = []
    return sorted(set(found))


def bump(db, workspace_id: str, keys: list[str]) -> VaultVersion:
    """Adds one to the student's Vault version and stamps it on each key, under the workspace lock (select, then
    update: it works on SQLite too). No commit."""
    db.get(Workspace, workspace_id, with_for_update=True, populate_existing=True)
    row = db.scalar(select(VaultVersion).where(VaultVersion.workspace_id == workspace_id)
                    .execution_options(populate_existing=True))
    if row is None:
        row = VaultVersion(workspace_id=workspace_id, version=0, key_versions={})
        db.add(row)
    row.version += 1
    row.key_versions = {**(row.key_versions or {}), **{k: row.version for k in keys}}
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def after_accept(db, candidate) -> None:
    """Reconciler hook (signature `hook(db, candidate)`, the writer's transaction)."""
    if not config.CONNECT_STUDENT_FACTS:
        return
    keys = keys_for(candidate, db)
    if not keys:
        return
    row = bump(db, candidate.workspace_id, keys)  # an error here propagates: the write must not lose its version
    try:
        with db.begin_nested():
            outbox.record_vault_event(db, candidate.workspace_id, row.version, keys)
    except Exception as exc:  # noqa: BLE001  (the sweep queues the event again from the version table)
        log.error("vault_event_queue_failed workspace_id=%s error_type=%s", candidate.workspace_id,
                  type(exc).__name__)
