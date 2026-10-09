"""Read-only, channel-neutral context for one deep Counselor turn."""

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import config
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.journey import JourneyService
from app.memory.episodic import EpisodicMemoryService
from app.memory.foreground import build_foreground_context
from app.memory.student_snapshot import StudentSnapshotService
from app.models import Roadmap, User, Workspace
from app.plugins._shared.sources import public_https

logger = logging.getLogger(__name__)
_NOTEBOOK_ORDER = (
    "open_questions", "coverage", "claims", "family", "constraints",
    "mirror_ready", "depth_mode", "engagement_style", "stated_goal", "person",
    "strengths", "growth_areas", "drivers", "hypotheses", "goal_history",
    "values", "learning_style", "work_preferences", "emotional_notes",
    "mirror_blockers", "chapter",
)


def estimated_tokens(value: str) -> int:
    """Conservative transport-independent estimate; no tokenizer/model call."""
    return math.ceil(len(value.encode("utf-8")) / 4)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _short(value: object, limit: int = 350) -> object:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return {key: _short(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_short(item, limit) for item in value]
    return value


def _trim_notebook(notebook) -> dict:
    source = notebook.model_dump(mode="json")
    selected: dict = {}
    for key in _NOTEBOOK_ORDER:
        value = _short(source[key])
        if isinstance(value, list):
            kept = []
            for item in value:
                candidate = {**selected, key: [*kept, item]}
                if estimated_tokens(_json(candidate)) > config.PAI_COUNSELOR_NOTEBOOK_CONTEXT_TOKENS:
                    break
                kept.append(item)
            value = kept
        candidate = {**selected, key: value}
        if estimated_tokens(_json(candidate)) <= config.PAI_COUNSELOR_NOTEBOOK_CONTEXT_TOKENS:
            selected[key] = value
    return selected


def _profile(db, workspace_id: str) -> dict:
    workspace = db.get(Workspace, workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace and workspace.owner_user_id else None
    snapshot = StudentSnapshotService(db).build(workspace_id)
    identity = {}
    if owner and owner.display_name:
        identity["display_name"] = {"value": owner.display_name, "source": "onboarding"}
    for key, fact in snapshot.facts.items():
        if key in {"preferred_name", "full_name", "date_of_birth", "current_status", "status_category"}:
            identity[key] = {"value": _short(fact.get("value")),
                             "source": fact.get("source_type") or "unknown"}
    facts = {key: {"value": _short(fact.get("value")),
                   "source": fact.get("source_type") or "unknown",
                   "verification": fact.get("confidence")}
             for key, fact in list(snapshot.facts.items())[:30] if key not in identity}
    records = {kind: [{"value": _short({field: value for field, value in row.items()
                                        if field not in {"evidence", "created_at", "updated_at"}}),
                       "source": row.get("source_type") or "unknown",
                       "verification": row.get("verification_status") or "unknown"}
                      for row in rows[:5]]
               for kind, rows in snapshot.records.items() if rows and kind in {
                   "education", "course", "certification", "test_attempt", "goal",
                   "work_experience", "project", "skill", "achievement", "activity",
               }}
    return {"identity_never_ask": identity, "facts": facts, "records": records,
            "open_profile_issues": [{"type": issue.get("type"), "question": issue.get("question")}
                                    for issue in snapshot.issues[:5]]}


def _research(db, workspace_id: str, journey) -> dict | None:
    if journey is None or (journey.counselor_summary_draft or {}).get("status") != "confirmed":
        return None
    rows = db.execute(select(Roadmap).where(
        Roadmap.workspace_id == workspace_id, Roadmap.journey_id == journey.id,
    ).order_by(Roadmap.created_at.desc()).limit(5)).scalars().all()
    return {"roadmaps": [{"id": row.id, "title": row.title,
                          "status": row.generation_status,
                          "sources": [item for item in (row.sources or [])[:5]
                                      if public_https(item.get("url") if isinstance(item, dict) else None)]}
                         for row in rows]}


@dataclass(frozen=True)
class DeepContext:
    text: str
    section_tokens: dict[str, int]
    notebook: object
    journey: object | None
    build_ms: int


async def build_context(db, workspace_id: str, turn: CounselorTurnInput, *,
                        roadmap_id: str | None = None) -> DeepContext:
    """Build every section from workspace-scoped reads; make no model calls."""
    started = time.monotonic()
    if workspace_id != turn.workspace_id:
        raise ValueError("turn belongs to another workspace")
    sections: dict[str, str] = {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "language_policy": _json({
            "blocked_scripts": [name.strip() for name in config.PAI_LANGUAGE_BLOCKED_SCRIPTS.split(",")
                                if name.strip()],
            "replacement": config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT,
            "fallback_reply": config.PAI_COUNSELOR_FALLBACK_REPLY,
        }),
        "profile": _json(_profile(db, workspace_id)),
    }
    notebook = NotebookService(db).get(workspace_id).notebook
    sections["notebook"] = _json(_trim_notebook(notebook))
    journey = next((item for item in JourneyService(db).list(workspace_id, status="active")
                    if item.journey_type == "counselor_decision"), None)
    memory_block = ""
    if config.PAI_MEMORY_CONTEXT_ENABLED and turn.student_text:
        memory = await build_foreground_context(
            workspace_id, turn.student_text, caller="pai", lexical_only=True)
        memory_block = memory.block
    recent = EpisodicMemoryService(db).recent(workspace_id, limit=1)
    sections["memory"] = _json({
        "foreground": memory_block,
        "latest_episode_summary": recent[0].summary[:500] if recent else None,
        "open_threads": [item.question_intent for item in notebook.open_questions[:3]],
    })
    research = _research(db, workspace_id, journey)
    if roadmap_id is not None:
        row = db.scalar(select(Roadmap).where(
            Roadmap.id == roadmap_id, Roadmap.workspace_id == workspace_id))
        if row is None:
            raise ValueError("roadmap belongs to another workspace or does not exist")
        research = {**(research or {}), "selected_roadmap": {
            "id": row.id, "title": row.title, "status": row.generation_status,
            "route": _short(row.route), "fit_dimensions": _short(row.fit_dimensions),
            "gaps": _short(row.gaps), "steps": _short(row.steps),
            "risks": _short(row.risks), "sources": _short(row.sources),
        }}
    if research is not None:
        sections["research"] = _json(research)
    draft = (journey.counselor_summary_draft or {}) if journey else {}
    sections["journey"] = _json({"stage": journey.current_stage if journey else "IDENTITY",
        "mirror_status": draft.get("status"), "mirror_notebook_version": draft.get("notebook_version")})
    text = "<context>\n" + "\n".join(
        f"<{name}>{value}</{name}>" for name, value in sections.items()
    ) + "\n</context>"
    counts = {name: estimated_tokens(value) for name, value in sections.items()}
    elapsed = int((time.monotonic() - started) * 1000)
    logger.info("counselor_deep_context tokens=%s total_tokens=%d build_ms=%d",
                counts, estimated_tokens(text), elapsed)
    return DeepContext(text, counts, notebook, journey, elapsed)
