"""The 360-degree path analyzer: one background worker behind the Counselor.

It looks at everything the student has shared (the Truth Map) and their
records, suggests general paths, and checks each path against the student:
what they already have, what they partly have, what blocks it, and what is not
known yet. Every known status cites the student's own evidence; anything the
model cannot cite becomes "unknown" here, in code, not by asking nicely.

Paths stay general (fields, kinds of qualification or work). Institutions,
fees and merit are research, not analysis, and never appear here.
"""

import hashlib
import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import config
from app.inference.gateway import complete as chat_completion, resolve_model
from app.journey import JourneyService
from app.models import BackgroundJob, EventRecord, Workspace
from app.pai_c.deep.analysis import _workspace_lock
from app.pai_c.deep.context import _json
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.memory import MemoryService
from app.pai_c.planner.view import build_planner_view
from app.pai_c.policy.controller import load_data
from app.pai_c.possibilities import PossibilityService
from app.pai_c.possibility_titles import normalized_title, valid_title
from app.pai_c.posting import send_to_student
from app.pai_c.understanding.data import at_path, load_policy as understanding_policy
from app.runtime.task_runtime import enqueue

logger = logging.getLogger(__name__)
JOB_ANALYZE_PATHS = "counselor.paths"


def policy() -> dict:
    return load_data("path_analyzer.json")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FitItem(_Strict):
    label: str = Field(min_length=1, max_length=200)
    status: Literal["have", "partial", "blocker", "unknown"]
    note: str = Field(default="", max_length=400)
    evidence_item_ids: list[str] = Field(default_factory=list)


class AnalyzedPath(_Strict):
    title: str = Field(min_length=1, max_length=120)
    why: str = Field(min_length=1, max_length=600)
    evidence_item_ids: list[str] = Field(default_factory=list)
    fit: list[FitItem] = Field(default_factory=list)


class PathAnalysis(_Strict):
    message: str = Field(min_length=1, max_length=1200)
    paths: list[AnalyzedPath] = Field(default_factory=list)


def _evidence_index(db, workspace_id: str, notebook) -> dict[str, str]:
    """Every id the analyzer may cite, mapped to the student's own words."""
    index: dict[str, str] = {}
    stored = notebook.model_dump(mode="json")
    for path in understanding_policy()["item_paths"]:
        for row in at_path(stored, path):
            if row.get("status", "active") == "active" and row.get("id") and row.get("evidence"):
                index[row["id"]] = str(row["evidence"])[:300]
    for card in MemoryService(db).profile_cards(workspace_id):
        quote = (card.get("source") or {}).get("quote")
        index[card["id"]] = str(quote or card.get("value"))[:300]
    return index


def _records(db, workspace_id: str) -> list[dict]:
    return [{"id": card["id"], "kind": card["kind"], "key": card["key"], "value": card["value"],
             "evidence_level": card["evidence_level"]}
            for card in MemoryService(db).profile_cards(workspace_id)]


def sanitize(analysis: PathAnalysis, evidence: dict[str, str], dismissed: set[str]) -> list[dict]:
    """Code-level honesty: drop world numbers, malformed titles and dismissed
    paths, cap counts, and turn any uncited verdict into "unknown"."""
    rules = policy()
    world_number = re.compile(load_data("grounding.json")["numeric_world_pattern"])
    evidenced = set(rules["evidenced_statuses"])
    kept, seen = [], set()
    for path in analysis.paths:
        key = normalized_title(path.title)
        if key in dismissed or key in seen:
            continue
        if not valid_title(path.title):
            logger.warning("path_analyzer_dropped_title words=%d", len(path.title.split()))
            continue
        if any(world_number.search(text) for text in (path.title, path.why)):
            logger.warning("path_analyzer_dropped_world_number")
            continue
        seen.add(key)
        fit = []
        for item in path.fit[:rules["max_fit_items"]]:
            ids = [i for i in dict.fromkeys(item.evidence_item_ids) if i in evidence]
            status = item.status if (item.status not in evidenced or ids) else "unknown"
            note = "" if world_number.search(item.note) else item.note
            fit.append({"label": item.label, "status": status, "note": note,
                        "evidence": [evidence[i] for i in ids] if status in evidenced else []})
        ids = [i for i in dict.fromkeys(path.evidence_item_ids) if i in evidence]
        kept.append({"title": path.title.strip(), "why": path.why.strip(), "fit": fit,
                     "evidence": [{"text": evidence[i], "item_id": i} for i in ids]})
        if len(kept) == rules["max_paths"]:
            break
    return kept


def enqueue_path_analysis(db, workspace_id: str, *, source_event_id: str | None,
                          channel: str | None, reason: str) -> str | None:
    """Queue one analysis per input: the Truth Map version and the paths the
    student typed in. A job not yet started is reused, since it reads both
    when it runs. The caller commits, as with the other Counselor enqueues."""
    snapshot = MemoryService(db).truth_map(workspace_id)
    pending = db.scalar(select(BackgroundJob.id).where(
        BackgroundJob.workspace_id == workspace_id, BackgroundJob.job_type == JOB_ANALYZE_PATHS,
        BackgroundJob.status == "pending"))
    if pending:
        return pending
    own = sorted(row.normalized_title for row in PossibilityService(db).list(workspace_id)
                 if row.source == "student" and row.status != "dismissed")
    digest = hashlib.sha256("|".join(own).encode()).hexdigest()[:16]
    payload = {"notebook_version": snapshot.version, "reason": reason,
               "source_event_id": source_event_id, "channel": channel}
    job = enqueue(db, JOB_ANALYZE_PATHS, {key: value for key, value in payload.items() if value is not None},
        workspace_id=workspace_id,
        idempotency_key=f"counselor:paths:{workspace_id}:{snapshot.version}:{digest}")
    return job.id if job else None


async def path_analysis_job(job, db) -> dict:
    if not job.workspace_id:
        raise ValueError("path analysis requires a workspace")
    payload = dict(job.payload or {})
    rules = policy()
    async with _workspace_lock(db, job.workspace_id):
        posted = db.scalar(select(EventRecord.id).where(
            EventRecord.network_id == job.workspace_id,
            EventRecord.metadata_["paths_job_id"].as_string() == job.id))
        if posted:
            return {"status": "posted", "message_id": posted}
        snapshot = MemoryService(db).truth_map(job.workspace_id)
        evidence = _evidence_index(db, job.workspace_id, snapshot.notebook)
        if len(evidence) < rules["min_notebook_items"]:
            return {"status": "not_enough_known", "items": len(evidence)}
        service = PossibilityService(db)
        existing = service.list(job.workspace_id)
        dismissed = {row.normalized_title for row in existing if row.status == "dismissed"}
        analyst_input = ("<limits>" + _json({"max_paths": rules["max_paths"], "max_fit_items": rules["max_fit_items"]}) + "</limits>\n"
            + build_planner_view(snapshot.notebook).text + "\n"
            + "<records>" + _json(_records(db, job.workspace_id)) + "</records>\n"
            + "<existing_paths>" + _json([{"title": row.title, "why": row.why} for row in existing if row.status != "dismissed"]) + "</existing_paths>\n"
            + "<dismissed_paths>" + _json([row.title for row in existing if row.status == "dismissed"]) + "</dismissed_paths>")
        db.rollback()
        prompt = load_prompt("path_analyzer")
        analysis = None
        for attempt in range(2):
            raw = await chat_completion(role="analyst",
                api_key=config.PAI_API_KEY, model=resolve_model("analyst"),
                system_prompt=prompt, messages=[{"role": "user", "content": analyst_input}],
                response_format={"type": "json_object"},
                reasoning_effort=config.PAI_ANALYST_REASONING_EFFORT,
                base_url=config.PAI_BASE_URL, turn_id=payload.get("source_event_id") or job.id)
            try:
                analysis = PathAnalysis.model_validate(json.loads(raw))
                break
            except (TypeError, ValueError):
                logger.warning("path_analyzer_invalid job_id=%s attempt=%d", job.id, attempt + 1)
                prompt += "\nReturn one complete JSON object that follows every output rule."
        if analysis is None:
            return {"status": "invalid", "model_calls": 2}
        paths = sanitize(analysis, evidence, dismissed)
        if not paths:
            return {"status": "no_paths"}
        workspace = db.scalar(select(Workspace).where(
            Workspace.id == job.workspace_id, Workspace.status == "active").with_for_update())
        if workspace is None:
            return {"status": "inactive"}
        journey = JourneyService(db).ensure_counselor(job.workspace_id)
        ids = []
        for path in paths:
            row = service.by_title(job.workspace_id, path["title"])
            if row is None:
                row = service.add(job.workspace_id, journey.id, title=path["title"], why=path["why"],
                    kind="discovered", source="analyzer", status="suggested", evidence=path["evidence"])
            if row.status == "dismissed":
                continue
            row.fit = path["fit"]
            ids.append(row.id)
        db.commit()
        channel = payload.get("channel")
        if not channel or not ids:
            return {"status": "stored", "paths": ids}
        message = await send_to_student(db, job.workspace_id, channel, "pai", analysis.message, 0,
            metadata={"paths_job_id": job.id, "paths_found": ids})
        if not message:
            raise RuntimeError("path analysis message was not persisted")
        return {"status": "posted", "message_id": message, "paths": ids}
