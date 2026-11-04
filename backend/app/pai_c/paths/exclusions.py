"""A field the student excluded stays dismissed (R-47 C1).

When the student rules a field out in chat ("remove Pharm-D", "only MBBS and
BDS"), the Vault holds a ruled-out `option` in their words. Its text is read
through the catalog's study_fields choice list (code, label or synonym), the
key family a path's `study_field["key"]` uses; text that names no field
changes nothing. A matching path the student has suggested, saved or is
exploring is dismissed with the option and the student's words
(`PaiPossibility.dismissal`), the analyzer never offers that field again, and
PAI says so once in a fixed sentence (exclusion.json). A chosen path is left
alone: the route decision owns it. The student restoring a dismissed path is
the undo: the same Vault option does not dismiss it again; a new one does.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.models import EventRecord, PaiPossibility, Workspace
from app.pai_c.memory import MemoryService, vault_catalog
from app.pai_c.policy.controller import load_data
from app.pai_c.possibilities import PossibilityService
from app.pai_c.posting import send_to_student
from app.runtime.task_runtime import enqueue

logger = logging.getLogger(__name__)
JOB_PATHS_EXCLUDED = "counselor.paths_excluded"
REASON = "student_excluded"
_OPEN = frozenset({"suggested", "saved", "exploring"})


def policy() -> dict:
    return json.loads(Path(__file__).with_name("exclusion.json").read_text(encoding="utf-8"))


def excluded_fields(db, workspace_id: str) -> dict[str, dict]:
    """Study field key -> the ruled-out option that names it (the latest one
    when several do). Options whose text names no field are left out."""
    catalog = vault_catalog()
    fields = {}
    for option in MemoryService(db).ruled_out_options(workspace_id):
        key = catalog.choice_code("study_fields", option["text"])
        if key:
            fields[key] = option
    return fields


def _restored(row: PaiPossibility, option: dict) -> bool:
    dismissal = row.dismissal or {}
    return dismissal.get("item_id") == option["item_id"] and bool(dismissal.get("restored_at"))


def _dismissal(option: dict) -> dict:
    return {"reason": REASON, "item_id": option["item_id"], "quote": option["quote"],
            "at": datetime.now(timezone.utc).isoformat()}


def apply_exclusions(db, workspace_id: str, excluded: dict[str, dict] | None = None) -> list[PaiPossibility]:
    """Dismiss every open path whose field the student ruled out, unless the
    student restored it against the same Vault option. A matching path the
    student had already dismissed by hand is only marked with the exclusion
    (no transition, no notice), so restoring it later is the undo there too.
    `excluded` is `excluded_fields`, when the caller already has it. Flushes;
    the caller commits. Returns the rows it dismissed."""
    excluded = excluded_fields(db, workspace_id) if excluded is None else excluded
    if not excluded:
        return []
    service = PossibilityService(db)
    changed = []
    for row in service.list(workspace_id):
        option = excluded.get((row.study_field or {}).get("key"))
        if option is None:
            continue
        if row.status == "dismissed" and (row.dismissal or {}).get("reason") != REASON:
            row.dismissal = _dismissal(option)
            continue
        if row.status not in _OPEN or _restored(row, option):
            continue
        service.transition(workspace_id, row.id, "dismiss")
        row.dismissal = _dismissal(option)
        changed.append(row)
    db.flush()
    if changed:
        logger.info("paths_excluded workspace_id=%s count=%d", workspace_id, len(changed))
    return changed


def hidden_field_keys(db, workspace_id: str, rows, excluded: dict[str, dict] | None = None) -> set[str]:
    """Fields the analyzer must not offer: every excluded field, except one
    whose path the student kept or restored (it stays theirs to reassess)."""
    kept = {(row.study_field or {}).get("key") for row in rows if row.status != "dismissed"}
    return set(excluded_fields(db, workspace_id) if excluded is None else excluded) - kept


def enqueue_exclusion_notice(db, workspace_id: str, rows, *, source_event_id: str | None) -> str | None:
    """Queue the one notice for these dismissed paths. The key names each
    path with the Vault option that dismissed it: a re-reconcile or retry
    reuses the job, a new exclusion after a restore is a new notice. The
    caller commits."""
    ids = sorted(row.id for row in rows)
    if not ids:
        return None
    pairs = sorted(f"{row.id}:{(row.dismissal or {}).get('item_id')}" for row in rows)
    payload = {"possibility_ids": ids, **({"source_event_id": source_event_id} if source_event_id else {})}
    job = enqueue(db, JOB_PATHS_EXCLUDED, payload, workspace_id=workspace_id,
                  idempotency_key=f"paths-excluded:{workspace_id}:{','.join(pairs)}")
    return job.id if job else None


def _titles(titles: list[str], rules: dict) -> str:
    if len(titles) == 1:
        return titles[0]
    return rules["list_separator"].join(titles[:-1]) + rules["list_last"] + titles[-1]


def _channel(db, workspace_id: str, source_event_id: str | None) -> str | None:
    """The channel of the student message behind the exclusion, else the
    channel of the student's latest message."""
    if source_event_id:
        target = db.scalar(select(EventRecord.target).where(
            EventRecord.network_id == workspace_id, EventRecord.id == source_event_id))
        if target:
            return target
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return None
    return db.scalar(select(EventRecord.target).where(
        EventRecord.network_id == workspace_id, EventRecord.type == "workspace.message.posted",
        EventRecord.source == f"human:{workspace.owner_user_id}")
        .order_by(EventRecord.timestamp.desc()).limit(1))


async def paths_excluded_job(job, db) -> dict:
    from app.jobs.service import JobDeferred
    from app.pai_c.myths import care_active
    from app.services.pai import PAI_AGENT_NAME
    if not job.workspace_id:
        raise ValueError("paths excluded notice requires a workspace")
    payload = dict(job.payload or {})
    posted = db.scalar(select(EventRecord.id).where(
        EventRecord.network_id == job.workspace_id,
        EventRecord.metadata_["paths_excluded_job_id"].as_string() == job.id))
    if posted:
        return {"status": "posted", "message_id": posted}
    if care_active(db, job.workspace_id):
        deferred = JobDeferred("The paths notice waits for care")
        deferred.delay_seconds = load_data("myths.json")["care_retry_seconds"]
        raise deferred
    ids = set(payload.get("possibility_ids") or [])
    # Only paths still dismissed for the student's exclusion: one they already
    # restored is not announced as removed.
    titles = [row.title for row in PossibilityService(db).list(job.workspace_id)
              if row.id in ids and row.status == "dismissed" and (row.dismissal or {}).get("reason") == REASON]
    if not titles:
        return {"status": "superseded"}
    channel = _channel(db, job.workspace_id, payload.get("source_event_id"))
    if not channel:
        return {"status": "no_channel"}
    rules = policy()
    message = rules["notice"]["one" if len(titles) == 1 else "other"].format(titles=_titles(titles, rules))
    event_id = await send_to_student(db, job.workspace_id, channel, PAI_AGENT_NAME, message, 0,
                                     metadata={"paths_excluded_job_id": job.id})
    if not event_id:
        raise RuntimeError("paths excluded notice was not persisted")
    return {"status": "posted", "message_id": event_id}
