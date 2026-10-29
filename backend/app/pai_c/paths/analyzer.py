"""The 360-degree path analyzer: one background worker behind the Counselor.

It looks at everything the student has shared (the Truth Map) and their
records, suggests paths, and checks each path against the student: what they
already have, what they partly have, what blocks it, and what is not known yet.
Every known status cites the student's own evidence; anything the model cannot
cite becomes "unknown" here, in code, not by asking nicely.

Paths are real fields of study (Electrical Engineering, MBBS, BBA), chosen
only from the fields the student's current education opens or may open
(paths/fields.candidate_fields). The saved title is the field's own title, and
there are 0 to 5 paths: a field without enough evidenced fit is dropped, never
padded. Institutions, fees and merit are research, not analysis, and never
appear here.
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
from app.pai_c.memory import RECORD_SPECS, MemoryService, display_text, result_text as _result_text, vault_catalog
from app.pai_c.paths.fields import Candidate, candidate_fields, current_education, read_education, study_fields
from app.pai_c.planner.view import build_planner_view
from app.pai_c.policy.controller import load_data
from app.pai_c.possibilities import PossibilityService
from app.pai_c.possibility_titles import normalized_title
from app.pai_c.posting import send_to_student
from app.pai_c.understanding.data import at_path, load_policy as understanding_policy
from app.plugins._shared.budget import take_daily
from app.workspace_language import workspace_language_block
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
    # field_key names a candidate study field; title is read only to
    # re-assess a path the student added in their own words.
    field_key: str = ""
    title: str = Field(default="", max_length=120)
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
        # The stored value, in the workspace language; the raw quote stays
        # backend evidence and is never shown on a path.
        index[card["id"]] = _card_text(card.get("value"), card.get("kind"), card.get("key"))[:300]
    return index


def _education_text(value: dict) -> str:
    """An education record in words: level, group or field and subjects
    through their catalog labels, so a path never shows "pre_engineering"."""
    catalog, rules = vault_catalog(), policy()
    level = catalog.choice_code("levels", str(value.get("qualification_name") or ""))
    lists = catalog.record_choice_fields(catalog.type("education"), value)

    def word(list_name, text):
        code = catalog.choice_code(list_name, text) if list_name else None
        return catalog.label(list_name, code) if code else text.replace("_", " ")

    parts = []
    for key, node in value.items():
        if key in rules["education_hidden_fields"] or key == "id" or key.endswith("_id"):
            continue
        if key == "academic_status":
            parts.append(rules["education_status_labels"].get(node, ""))
        elif key == "result" and isinstance(node, dict):
            parts.append(_result_text(node))
        elif key == "details" and isinstance(node, dict):
            parts.extend(word(f"{level}_subjects", str(s)) for s in node.get("subjects") or [])
        elif isinstance(node, str):
            parts.append(word(lists.get(key), node))
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            parts.append(str(node))
    return ", ".join(part for part in parts if part and part.strip())


# Record kinds outside the catalog that still read as the Vault page shows them.
_DISPLAYED_RECORDS = frozenset(RECORD_SPECS)


def _card_text(value, kind: str | None = None, key: str | None = None) -> str:
    """Evidence words for a profile card. With its catalog key, a card reads
    exactly as the Vault page shows it (labels, "470/550 (85%)", a budget
    band), never as "pre_engineering, current" or "600000"."""
    if kind == "education" and isinstance(value, dict):
        return _education_text(value)
    if (key and vault_catalog().type(key) is not None) or kind in _DISPLAYED_RECORDS:
        return display_text(key or kind, value)
    if isinstance(value, dict):
        return ", ".join(str(item) for item in value.values() if isinstance(item, (str, int, float)) and str(item).strip())
    return str(value)


def _records(db, workspace_id: str) -> list[dict]:
    return [{"id": card["id"], "kind": card["kind"], "key": card["key"], "value": card["value"],
             "evidence_level": card["evidence_level"]}
            for card in MemoryService(db).profile_cards(workspace_id)]


def _vault_sources(db, workspace_id: str, records: list[dict]) -> dict[str, dict]:
    """Every citable Vault entry (a profile card: fact, record or item) with
    the badge a path shows next to its reason, exactly as the Vault page shows
    it: the Vault view's level (one ladder, so an agent's "stated" is "PAI's
    guess" here too) and where it came from, labelled as the Mirror labels its
    entries (document name, onboarding, details or chat)."""
    from app.pai_c.mirror.engine import source_label
    badges = {}
    for row in MemoryService(db).vault_rows(workspace_id):
        entry = row.entry
        badges[("item:" if entry["kind"] == "item" else "") + str(entry["id"])] = {
            "evidence_level": entry["level"], "source_label": source_label(row)}
    return {card["id"]: badges[card["id"]] for card in records if card["id"] in badges}


# Recall kinds that name a Vault entry; their hit id is the entry's own id.
_VAULT_RECALL_KINDS = ("vault_fact", "vault_item", "student_record:")


def _recall_query(fields: list[dict], records: list[dict]) -> str:
    """What the student could study and what they want: the candidate field
    titles and the Vault entries of the types `recall_query_types` names."""
    types = set(policy().get("recall_query_types", ()))
    wanted = [_card_text(card["value"], card["kind"], card["key"]) for card in records if card["key"] in types]
    # What the student wants leads, so a long candidate list does not drown it.
    return "; ".join(part for part in [*wanted, *(field["title"] for field in fields)] if part)


async def _semantic_recall(db, workspace_id: str, query: str, citable: set[str]) -> list[dict]:
    """Embeddings recall as extra evidence (FOUR_FEATURES_SPEC 3). A hit on a
    Vault entry carries its profile-card id, so the model can cite it and
    sanitize accepts it. A Vault hit that is not a card (sensitive, or only
    PAI's guess) is left out, since the cards exclude it on purpose. Any other
    hit (a session summary, a document passage) has no Vault entry behind it:
    it is shown with id null, as context the model cannot cite. Recall off or
    empty gives no block."""
    if not query:
        return []
    try:
        hits = await MemoryService(db).recall(workspace_id, query, top_k=policy().get("recall_top_k", 8))
    except Exception as exc:  # noqa: BLE001  every feature works without recall (spec 1.3)
        logger.warning("path_analyzer_recall_failed workspace_id=%s error_type=%s", workspace_id, type(exc).__name__)
        return []
    shown, seen = [], set()
    for hit in hits:
        kind = str(hit.get("kind") or "")
        if kind.startswith(_VAULT_RECALL_KINDS):
            ref = ("item:" if kind == "vault_item" else "") + str(hit["id"])
            if ref not in citable or ref in seen:
                continue
            seen.add(ref)
            shown.append({"id": ref, "kind": kind, "text": str(hit.get("text") or "")[:300]})
        elif hit.get("text"):
            shown.append({"id": None, "kind": kind, "text": str(hit["text"])[:300]})
    return shown


def _study_field(candidate: Candidate) -> dict:
    """What the workspace shows and PAI OS reads; the ISCED code is never shown."""
    return {"key": candidate.field.key, "isced": candidate.field.isced,
            "needs_check": candidate.standing == "check",
            "needs_group": [{"code": code, "label": vault_catalog().label("intermediate_groups", code)}
                            for code in candidate.needs_group]}


def sanitize(analysis: PathAnalysis, evidence: dict[str, str], dismissed: set[str],
             candidates: dict[str, Candidate], own: set[str] = frozenset(), *,
             vault: dict[str, dict]) -> list[dict]:
    """Code-level honesty: keep only candidate fields (titled by the field,
    never by the model) or the student's own paths, drop world numbers,
    dismissed paths, paths whose why cites no Vault entry (`vault`: card id ->
    evidence level and source label) and fields without enough evidenced fit,
    cap the count, and turn any uncited verdict into "unknown". Zero paths is
    a valid result. A field outside the candidates is one the student's group
    rules out. The student's own paths are re-assessed first; fields fill the
    rest of the cap."""
    rules = policy()
    world_number = re.compile(load_data("grounding.json")["numeric_world_pattern"])
    evidenced = set(rules["evidenced_statuses"])
    fitting = set(rules["fit_evidence_statuses"])
    kept, seen = [], set()

    def is_own(path):
        return path.field_key not in candidates and normalized_title(path.title) in own

    for path in sorted(analysis.paths, key=lambda path: not is_own(path)):
        candidate = candidates.get(path.field_key)
        if candidate is not None:
            title = candidate.field.title
        elif path.title.strip() and normalized_title(path.title) in own:
            title = path.title.strip()
        else:
            logger.warning("path_analyzer_dropped_not_a_candidate")
            continue
        key = normalized_title(title)
        if key in dismissed or key in seen:
            continue
        if world_number.search(path.why):
            logger.warning("path_analyzer_dropped_world_number")
            continue
        cited = [i for i in dict.fromkeys(path.evidence_item_ids) if i in evidence]
        if not any(i in vault for i in cited):
            # The why must rest on the Vault (FOUR_FEATURES_SPEC 3), not
            # only on the notebook or nothing.
            logger.warning("path_analyzer_dropped_uncited_why field=%s", path.field_key or "own")
            continue
        fit = []
        for item in path.fit[:rules["max_fit_items"]]:
            ids = [i for i in dict.fromkeys(item.evidence_item_ids) if i in evidence]
            status = item.status if (item.status not in evidenced or ids) else "unknown"
            note = "" if world_number.search(item.note) else item.note
            fit.append({"label": item.label, "status": status, "note": note,
                        "evidence": [evidence[i] for i in ids] if status in evidenced else []})
        if candidate is not None and sum(item["status"] in fitting for item in fit) < rules["min_fit_evidence"]:
            logger.warning("path_analyzer_dropped_weak_fit field=%s", candidate.field.key)
            continue
        seen.add(key)
        kept.append({"title": title, "why": path.why.strip(), "fit": fit,
                     "evidence": [{"text": evidence[i], "item_id": i,
                                   "evidence_level": vault.get(i, {}).get("evidence_level"),
                                   "source_label": vault.get(i, {}).get("source_label")} for i in cited],
                     "study_field": _study_field(candidate) if candidate is not None else None})
        if len(kept) == rules["max_paths"]:
            break
    return kept


def _prune(service: PossibilityService, rows, candidates: dict[str, Candidate], returned: set[str]) -> None:
    """Every finished run leaves only what this run stands behind.

    A suggested field that is outside today's candidates or was not returned
    again (weak fit, the group changed) is removed. A field the student saved,
    is exploring or chose stays, with its group notes refreshed, and is marked
    out_of_group when the student's current group no longer opens it (not when
    the education is simply unknown). Paths from before fields of study
    (generic titles such as "Computer use") give way the same way: removed
    when suggested, kept and marked outdated otherwise. The student's own
    paths, Mirror lanes (general directions, not fields) and dismissed rows
    are left alone."""
    titles = {normalized_title(field.title) for field in study_fields().values()}
    for row in rows:
        if row.source in {"student", "mirror"} or row.status == "dismissed":
            continue
        key = (row.study_field or {}).get("key")
        if row.status == "suggested":
            if key not in candidates or key not in returned:
                service.db.delete(row)
            continue
        if key in candidates:
            row.study_field = _study_field(candidates[key])
        elif key:
            if candidates and not row.study_field.get("out_of_group"):
                row.study_field = {**row.study_field, "out_of_group": True}
        elif row.normalized_title not in titles and row.study_field != {"outdated": True}:
            row.study_field = {"outdated": True}
    service.db.flush()


def enqueue_after_planner(db, workspace_id: str, *, source_event_id: str | None) -> str | None:
    """The planner saw a direction worth checking. The analyzer stays the one
    source of paths, so the planner only asks it to look again, at most once
    per cooldown so a run of turns does not re-analyse every time."""
    from datetime import datetime, timedelta, timezone
    latest = db.scalar(select(BackgroundJob.created_at).where(
        BackgroundJob.workspace_id == workspace_id, BackgroundJob.job_type == JOB_ANALYZE_PATHS)
        .order_by(BackgroundJob.created_at.desc()).limit(1))
    if latest is not None:
        latest = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - latest < timedelta(minutes=policy()["planner_cooldown_minutes"]):
            return None
    return enqueue_path_analysis(db, workspace_id, source_event_id=source_event_id, channel=None, reason="planner")


def _education_candidates(education: list[dict]) -> dict[str, Candidate]:
    """The fields the student's current education opens; records newest first."""
    return candidate_fields(current_education(education))


def enqueue_path_analysis(db, workspace_id: str, *, source_event_id: str | None,
                          channel: str | None, reason: str) -> str | None:
    """Queue one analysis per input: the Truth Map version, the paths the
    student typed in and the path-relevant Vault (`relevance_version` over
    `vault_trigger_types`, which includes education records as last written),
    so any education change is a new run even when nothing else changed. A job
    not yet started is reused, since it reads all of them when it runs. The
    caller commits, as with the other Counselor enqueues."""
    snapshot = MemoryService(db).truth_map(workspace_id)
    pending = db.scalar(select(BackgroundJob).where(
        BackgroundJob.workspace_id == workspace_id, BackgroundJob.job_type == JOB_ANALYZE_PATHS,
        BackgroundJob.status == "pending").limit(1))
    asked = reason == "asked" and bool(channel)
    if pending:
        if asked:
            # A chat request outranks a quiet (Vault or planner) run: the
            # pending run answers the student in their channel.
            pending.payload = {**_with_post_to(pending.payload, channel, source_event_id), "reason": "asked",
                               "channel": channel,
                               **({"source_event_id": source_event_id} if source_event_id else {})}
        return pending.id
    own = sorted(row.normalized_title for row in PossibilityService(db).list(workspace_id)
                 if row.source == "student" and row.status != "dismissed")
    # Every relevant write changes the key (each entry's id and updated_at),
    # so going back to an earlier group is a fresh run too, not the finished
    # job from the first time the student was in it.
    from app.pai_c.paths.currency import current_relevance
    digest = hashlib.sha256(("|".join(own) + "#" + current_relevance(db, workspace_id)).encode()).hexdigest()[:16]
    payload = {"notebook_version": snapshot.version, "reason": reason,
               "source_event_id": source_event_id, "channel": channel}
    key = f"counselor:paths:{workspace_id}:{snapshot.version}:{digest}"
    existing = db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == key))
    if asked and existing is not None and existing.status == "running":
        # The run re-reads `post_to` just before it posts, so a late ask is answered.
        existing.payload = _with_post_to(existing.payload, channel, source_event_id)
        return existing.id
    if asked and existing is not None and (existing.status == "failed"
                                           or (existing.result or {}).get("status") == "daily_cap"):
        # A failed (or capped quiet) run under the same input is retried once
        # per asking turn, rather than answering the student with nothing.
        key += f":retry:{source_event_id or 'ask'}"
    job = enqueue(db, JOB_ANALYZE_PATHS, {key_: value for key_, value in payload.items() if value is not None},
        workspace_id=workspace_id, idempotency_key=key)
    return job.id if job else None


def _with_post_to(payload, channel: str, source_event_id: str | None) -> dict:
    return {**(payload or {}), "post_to": {"channel": channel, "reason": "asked",
                                           **({"source_event_id": source_event_id} if source_event_id else {})}}


def _post_target(db, job, payload: dict) -> dict:
    """The payload as it is now, re-read just before posting (one SELECT):
    a chat ask recorded on the job while it ran (`post_to`) wins."""
    current = db.scalar(select(BackgroundJob.payload).where(BackgroundJob.id == job.id)) or {}
    post_to = current.get("post_to") or payload.get("post_to")
    if not post_to:
        return payload
    return {**payload, "reason": post_to["reason"], "channel": post_to["channel"],
            **({"source_event_id": post_to["source_event_id"]} if post_to.get("source_event_id") else {})}


async def ask_path_analysis(db, workspace_id: str, *, source_event_id: str | None,
                            channel: str) -> str | None:
    """The student asked in chat which paths they have. A pending run takes
    over the channel (enqueue_path_analysis). A finished run for the same
    input is not run again: its result is posted now, as the run would have
    posted it, once per asking turn. The caller commits."""
    job_id = enqueue_path_analysis(db, workspace_id, source_event_id=source_event_id,
                                   channel=channel, reason="asked")
    job = db.get(BackgroundJob, job_id) if job_id else None
    if job is None or job.status != "succeeded":
        return job_id
    replied = db.scalar(select(EventRecord.id).where(
        EventRecord.network_id == workspace_id,
        EventRecord.metadata_["paths_reply_to"].as_string() == (source_event_id or job.id)))
    if not replied:
        await _post_finished(db, job, channel, source_event_id or job.id)
        if (job.result or {}).get("paths"):
            # Answering the ask with saved paths is the student's act too: it
            # ends a re-plan as a fresh asked run would (journey_sync).
            from app.pai_c.journey_sync import sync_counselor_stage
            try:
                with db.begin_nested():
                    sync_counselor_stage(db, workspace_id, reason="asked", actor="system:paths")
            except Exception as exc:  # noqa: BLE001  the answer outranks the stage move
                logger.error("paths_stage_move_failed workspace_id=%s error_type=%s",
                             workspace_id, type(exc).__name__)
    return job_id


def _sync_stage(db, workspace_id: str, reason: str | None) -> None:
    """Saved paths move the journey on through the one stage sync (MIRROR ->
    PROPOSED, FOUR_FEATURES_SPEC 2.4). The paths are saved; a stage problem
    must not undo them."""
    from app.pai_c.journey_sync import sync_counselor_stage
    try:
        sync_counselor_stage(db, workspace_id, reason=reason or "paths", actor="system:paths")
        db.commit()
    except Exception as exc:  # noqa: BLE001  the saved paths outrank the stage move
        db.rollback()
        logger.error("paths_stage_move_failed workspace_id=%s error_type=%s",
                     workspace_id, type(exc).__name__)


async def _post_finished(db, job, channel: str, reply_to: str) -> None:
    result = job.result or {}
    if result.get("status") == "needs_education":
        education = [card["value"] for card in _records(db, job.workspace_id) if card["kind"] == "education"]
        await _needs_education(db, job, {"channel": channel, "reason": "asked"}, education,
                               extra={"paths_reply_to": reply_to})
        return
    paths = result.get("paths") or []
    if not paths:
        return
    message = result.get("message")
    if not message and result.get("message_id"):
        event = db.get(EventRecord, result["message_id"])
        message = ((event.payload or {}).get("content") if event else None)
    message = message or policy()["paths_found_message"]
    posted = await send_to_student(db, job.workspace_id, channel, "pai", message, 0,
        metadata={"paths_job_id": job.id, "paths_found": paths, "paths_reply_to": reply_to})
    if not posted:
        raise RuntimeError("path analysis message was not persisted")


def after_accept(db, candidate) -> None:
    """Reconciler hook: a write to a path-relevant Vault type
    (`vault_trigger_types`) queues the Path engine (reason "vault"). The
    enqueue is idempotent on the relevance version and the student's own
    paths, and a pending run is reused. Like the Mirror hook, it runs in a
    savepoint and never undoes the Vault write."""
    from app.pai_c.paths.currency import trigger_types
    try:
        if candidate.key not in trigger_types():
            return
        with db.begin_nested():
            enqueue_path_analysis(db, candidate.workspace_id, source_event_id=None, channel=None, reason="vault")
    except Exception as exc:  # noqa: BLE001  the Vault write outranks its read model
        logger.error("path_analysis_enqueue_failed workspace_id=%s error_type=%s",
                     candidate.workspace_id, type(exc).__name__)


def _reply_to(payload: dict) -> dict:
    """The asking turn a post answers, so a retried turn does not post twice."""
    return {"paths_reply_to": payload["source_event_id"]} if payload.get("source_event_id") else {}


async def _needs_education(db, job, payload: dict, education: list[dict], extra: dict | None = None) -> dict:
    """A student who asked in chat hears, in one short line, what PAI still
    needs (their group, subjects, field or education); the copy is data."""
    rules = policy()
    channel = payload.get("channel")
    if not channel or payload.get("reason") not in rules["needs_education_post_reasons"]:
        return {"status": "needs_education"}
    current = current_education(education)
    level = read_education(current)[0] if current else None
    message = rules["needs_education_messages"][rules["needs_education_by_level"].get(level, "education")]
    posted = await send_to_student(db, job.workspace_id, channel, "pai", message, 0,
                                   metadata={"paths_job_id": job.id, "paths_found": [], **(extra or {})})
    if not posted:
        raise RuntimeError("path analysis message was not persisted")
    return {"status": "needs_education", "message_id": posted}


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
        service = PossibilityService(db)
        records = _records(db, job.workspace_id)
        education = [card["value"] for card in records if card["kind"] == "education"]
        candidates = _education_candidates(education)
        if not candidates:
            # No education, or one PAI cannot place yet: no paths, and the
            # workspace shows what PAI still needs instead of a guess. Decided
            # before the notebook is counted, so a group change prunes the old
            # suggestions even for a student who has said little yet.
            _prune(service, service.list(job.workspace_id), {}, set())
            db.commit()
            payload = _post_target(db, job, payload)
            return await _needs_education(db, job, payload, education,
                                          extra=_reply_to(payload))
        evidence = _evidence_index(db, job.workspace_id, snapshot.notebook)
        if len(evidence) < rules["min_notebook_items"]:
            return {"status": "not_enough_known", "items": len(evidence)}
        existing = service.list(job.workspace_id)
        dismissed = {row.normalized_title for row in existing if row.status == "dismissed"}
        own = {row.normalized_title for row in existing if row.source == "student" and row.status != "dismissed"}
        fields = [{"key": c.field.key, "title": c.field.title, "family": c.field.family, "standing": c.standing}
                  | ({"needs_group": [vault_catalog().label("intermediate_groups", g) for g in c.needs_group]}
                     if c.needs_group else {}) for c in candidates.values()]
        vault = _vault_sources(db, job.workspace_id, records)
        reassess = []
        for row in existing:
            if row.status == "dismissed":
                continue
            if (row.study_field or {}).get("key"):
                reassess.append({"field_key": row.study_field["key"], "title": row.title, "why": row.why})
            elif row.source == "student":
                reassess.append({"title": row.title, "why": row.why, "own": True})
        analyst_input = ("<limits>" + _json({"max_paths": rules["max_paths"], "max_fit_items": rules["max_fit_items"],
                                             "min_fit_evidence": rules["min_fit_evidence"]}) + "</limits>\n"
            + build_planner_view(snapshot.notebook).text + "\n"
            + "<records>" + _json(records) + "</records>\n"
            + "<fields>" + _json(fields) + "</fields>\n"
            + workspace_language_block() + "\n"
            + "<existing_paths>" + _json(reassess) + "</existing_paths>\n"
            + "<dismissed_paths>" + _json([row.title for row in existing if row.status == "dismissed"]) + "</dismissed_paths>")
        # Daily cap on model runs (cost): a quiet run over it is skipped, one
        # that answers a chat ask still runs (and is counted).
        within = take_daily(db, job.workspace_id, "path_analysis", config.PAI_PATH_ANALYSIS_MAX_PER_DAY)
        db.commit()
        if not within and _post_target(db, job, payload).get("reason") != "asked":
            logger.warning("path_analysis_daily_cap workspace_id=%s", job.workspace_id)
            return {"status": "daily_cap"}
        # No read transaction stays open across the embedding call or the model call.
        db.rollback()
        recall = await _semantic_recall(db, job.workspace_id, _recall_query(fields, records),
                                        set(vault) & set(evidence))
        if recall:
            analyst_input += "\n<semantic_recall>" + _json(recall) + "</semantic_recall>"
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
        paths = sanitize(analysis, evidence, dismissed, candidates, own, vault=vault)
        workspace = db.scalar(select(Workspace).where(
            Workspace.id == job.workspace_id, Workspace.status == "active").with_for_update())
        if workspace is None:
            return {"status": "inactive"}
        _prune(service, service.list(job.workspace_id), candidates,
               {path["study_field"]["key"] for path in paths if path["study_field"]})
        if not paths:
            db.commit()
            return {"status": "no_paths"}
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
            if row.source != "mirror":
                # Re-rendered evidence: older rows may still quote raw codes.
                row.evidence = path["evidence"] or [
                    {**item, "text": evidence.get(item.get("item_id"), item["text"])} for item in row.evidence]
            if path["study_field"] is not None:
                row.study_field = path["study_field"]
            ids.append(row.id)
        db.commit()
        payload = _post_target(db, job, payload)
        if ids:
            _sync_stage(db, job.workspace_id, payload.get("reason"))
        channel = payload.get("channel")
        if not channel or not ids:
            # The message is kept so a later chat request can post it unchanged.
            return {"status": "stored", "paths": ids, "message": analysis.message}
        message = await send_to_student(db, job.workspace_id, channel, "pai", analysis.message, 0,
            metadata={"paths_job_id": job.id, "paths_found": ids, **_reply_to(payload)})
        if not message:
            raise RuntimeError("path analysis message was not persisted")
        return {"status": "posted", "message_id": message, "paths": ids}
