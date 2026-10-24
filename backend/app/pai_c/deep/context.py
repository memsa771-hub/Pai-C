"""Read-only, channel-neutral context for one deep Counselor turn."""

import json
from copy import deepcopy
from app.pai_c.understanding.data import at_path, set_path, load_policy
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import config
from app.pai_c.memory import MemoryService, estimated_tokens, select_context_entries  # noqa: F401  imported from here elsewhere
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.journey import JourneyService
from app.models import Roadmap, User, Workspace
from app.plugins._shared.sources import public_https

logger = logging.getLogger(__name__)
_NOTEBOOK_ORDER = (
    "schema_version", "open_questions", "coverage", "said", "source",
    "world.people", "world.daily_life", "world.social", "world.responsibilities", "world.education_story", "pressures",
    "self", "sure", "shown", "mirror_ready", "depth_mode", "engagement_style",
    "hypotheses", "goal_history", "tensions", "identity_status",
    "decision_difficulties", "private_notes", "mirror_blockers", "chapter",
)


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


def _trim_notebook(notebook, sensitive_types=frozenset()) -> dict:
    """The notebook within its token budget. People (with their wishes and
    worries) and pressures are as sensitive as the Vault types they mirror, so
    they come in only when `sensitive_types` (the Vault topic gate for this
    turn) holds that type."""
    from app.memory.vault_context import context_policy
    source = notebook.model_dump(mode="json")
    selected: dict = {}
    active_paths = (*load_policy()["item_paths"], load_policy()["person_path"])
    gates = context_policy()["notebook_gates"]
    for key in _NOTEBOOK_ORDER:
        if key in gates and gates[key] not in sensitive_types:
            continue
        value = _short(at_path(source, key))
        if key in active_paths:
            value = [item for item in value if item.get("status", "active") == "active"]
        if key == "pressures":
            value["items"] = [item for item in value["items"] if item.get("status", "active") == "active"]
        if isinstance(value, list):
            kept = []
            for item in value:
                candidate = deepcopy(selected)
                set_path(candidate, key, [*kept, item])
                if estimated_tokens(_json(candidate)) > config.PAI_COUNSELOR_NOTEBOOK_CONTEXT_TOKENS:
                    break
                kept.append(item)
            value = kept
        candidate = deepcopy(selected)
        set_path(candidate, key, value)
        if estimated_tokens(_json(candidate)) <= config.PAI_COUNSELOR_NOTEBOOK_CONTEXT_TOKENS:
            selected = candidate
    return selected


_IDENTITY_KEYS = ("identity.preferred_name", "identity.full_name", "identity.date_of_birth",
                  "identity.current_status", "identity.status_category")


def _previous_counselor_text(db, workspace_id: str, turn) -> str:
    """The counselor's last chat message before this turn: a short answer
    ("haan, woh chahte hain") names its topic only through that question."""
    from app.models import EventRecord
    query = select(EventRecord).where(
        EventRecord.network_id == workspace_id, EventRecord.type == "workspace.message.posted",
        EventRecord.source == "openagents:pai")
    query = (query.where(EventRecord.timestamp < turn.timestamp) if turn.timestamp is not None
             else query.where(EventRecord.id != turn.source_event_id))
    for row in db.scalars(query.order_by(EventRecord.timestamp.desc(), EventRecord.id.desc()).limit(3)):
        payload = row.payload or {}
        if payload.get("message_type", "chat") == "chat" and isinstance(payload.get("content"), str):
            return payload["content"][:1500]
    return ""


def _profile(db, workspace_id: str, snapshot=None, *, student_text: str = "", trigger_text: str = "",
             topics=()) -> dict:
    """Identity never to ask again, plus the Vault entries this turn may see."""
    workspace = db.get(Workspace, workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace and workspace.owner_user_id else None
    memory = MemoryService(db)
    snapshot = snapshot if snapshot is not None else memory.profile(workspace_id)
    identity = {}
    if owner and owner.display_name:
        identity["display_name"] = {"value": owner.display_name, "source": "onboarding"}
    for key in _IDENTITY_KEYS:
        if key in snapshot.facts and not memory.is_restricted(key):
            identity[key] = {"value": _short(snapshot.facts[key].get("value")),
                             "source": snapshot.facts[key].get("source_type") or "unknown"}
    return {"identity_never_ask": identity,
            **memory.counselor_vault(workspace_id, student_text, trigger_text=trigger_text, topics=topics,
                                     exclude_types=set(identity))}


def _research(db, workspace_id: str, journey) -> dict | None:
    if journey is None or (journey.counselor_summary_draft or {}).get("status") != "confirmed":
        return None
    rows = db.execute(select(Roadmap).where(
        Roadmap.workspace_id == workspace_id, Roadmap.journey_id == journey.id,
    ).order_by(Roadmap.created_at.desc()).limit(5)).scalars().all()
    from app.models import RequirementSet, Opportunity
    requirements = db.scalars(select(RequirementSet).join(Opportunity).where(
        Opportunity.workspace_id == workspace_id,
        RequirementSet.id.in_([row.requirement_set_id for row in rows if row.requirement_set_id]))).all()
    facts = [{**fact, "status": requirement.status} for requirement in requirements
             for fact in (requirement.rules or []) if isinstance(fact, dict)]
    return {"facts": facts[:20],
            "roadmaps": [{"id": row.id, "title": row.title,
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
    plan: object | None = None
    fact_cards: tuple = ()
    world_facts: tuple = ()


def guided_state(db, workspace_id, notebook, draft, decision, coverage, open_requests):
    """Compact counseling state for the guided Voice: what is known, missing and recent."""
    from app.models import CounselorTurnDecision, PaiPossibility
    chosen = db.scalar(select(PaiPossibility.id).where(
        PaiPossibility.workspace_id == workspace_id, PaiPossibility.status == "chosen").limit(1))
    if chosen is not None:
        stage = "chosen"
    elif draft.get("status") == "confirmed":
        stage = "options_ready"
    elif notebook.mirror_ready:
        stage = "mirror_ready"
    elif decision.action == "first_picture":
        stage = "first_picture_due"
    else:
        stage = "getting_to_know"
    rows = db.scalars(select(CounselorTurnDecision).where(CounselorTurnDecision.workspace_id == workspace_id)
        .order_by(CounselorTurnDecision.source_timestamp.desc(), CounselorTurnDecision.id.desc()).limit(3)).all()
    return {"stage": stage,
            "areas": {area: {key: row.get(key) for key in ("covered", "item_count", "min_items")}
                      for area, row in coverage.items()},
            "open_requests": open_requests[:5],
            "last_moves": [{"action": (row.decision or {}).get("action") or row.move, "moves": row.moves or []}
                           for row in reversed(rows)],
            "question_allowed": decision.question_allowed}


async def build_context(db, workspace_id: str, turn: CounselorTurnInput, *,
                        roadmap_id: str | None = None, wellbeing: bool = False,
                        decision=None, signals=None, mirror: bool = False) -> DeepContext:
    """Build every section from workspace-scoped reads; make no model calls."""
    started = time.monotonic()
    if workspace_id != turn.workspace_id:
        raise ValueError("turn belongs to another workspace")
    snapshot = MemoryService(db).profile(workspace_id)
    plan = MemoryService(db).latest_plan(workspace_id)
    # The areas the counselor is exploring also name a sensitive topic.
    topics = [topic for topic in (getattr(decision, "topic", None), getattr(plan, "target_gap", None)) if topic]
    trigger_text = _previous_counselor_text(db, workspace_id, turn)
    sections: dict[str, str] = {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "language_policy": _json({
            "blocked_scripts": [name.strip() for name in config.PAI_LANGUAGE_BLOCKED_SCRIPTS.split(",")
                                if name.strip()],
            "replacement": config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT,
            "fallback_reply": config.PAI_COUNSELOR_FALLBACK_REPLY,
        }),
        "profile": _json(_profile(db, workspace_id, snapshot, student_text=turn.student_text,
                                  trigger_text=trigger_text, topics=topics)),
    }
    memory = MemoryService(db)
    notebook = memory.truth_map(workspace_id).notebook
    if mirror:
        # Allowlist public views before serialization; private interpretation is
        # never carried through the general Voice notebook projection.
        public = memory.personal_view(workspace_id)
        public.update({key: [item.model_dump(mode="json") for item in getattr(notebook, key)
                             if item.status == "active"] for key in ("said", "shown")})
        public["depth_mode"] = notebook.depth_mode
        sections["notebook"] = _json(public)
        sections["personal_view"] = _json(memory.personal_view(workspace_id))
        sections["capability_view"] = _json(memory.capability_view(workspace_id))
        sections["private_gap_context"] = _json([
            {"between": item.between, "evidence": item.evidence, "status": item.status}
            for item in notebook.tensions])
    else:
        from app.memory.vault_context import sensitive_types_for
        sections["notebook"] = _json(_trim_notebook(
            notebook, sensitive_types_for(f"{trigger_text} {turn.student_text}", topics)))
    from app.pai_c.deep.noted_questions import NotedQuestionService
    sections["open_requests"] = _json(NotedQuestionService(db).open_requests(workspace_id))
    journey = next((item for item in JourneyService(db).list(workspace_id, status="active")
                    if item.journey_type == "counselor_decision"), None)
    memory = MemoryService(db)
    recent = memory.session_summaries(workspace_id, limit=2) if memory.is_return_visit(workspace_id) else []
    sections["memory"] = _json({
        "latest_episode_summary": recent[0].summary[:500] if recent else None,
        "session_summaries": [{"summary": row.summary, "entities": row.entities} for row in recent],
        "open_threads": [item.question_intent for item in notebook.open_questions[:3]],
    })
    if plan is not None and not mirror:
        if not wellbeing and plan.next_move != "care" and plan.playbooks:
            from app.pai_c.playbooks.registry import selected_playbooks
            sections["playbooks"] = selected_playbooks(plan.playbooks)
    if decision is not None and not wellbeing:
        from app.pai_c.policy.controller import decision_context
        possibility = None
        if decision.action == "discover":
            from app.pai_c.possibilities import PossibilityService
            possibility = PossibilityService(db).get(workspace_id, decision.topic)
        sections["decision"] = _json(decision_context(decision, signals, plan, possibility))
    research = _research(db, workspace_id, journey)
    from app.pai_c.myths import information_facts
    requested_facts = information_facts(db, workspace_id)
    if requested_facts:
        research = {**(research or {}), "facts": [*(research or {}).get("facts", []), *requested_facts]}
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
    if decision is not None and decision.action == "guide" and journey is not None:
        from app.pai_c.roadmaps.service import RoadmapService
        from app.pai_c.policy.controller import load_data
        ready = [row for row in RoadmapService(db).list(workspace_id)
                 if row["journey_id"] == journey.id and row["generation_status"] == "ready"]
        compare = []
        for row in ready[:load_data("guide.json")["compare_max_roadmaps"]]:
            entry = {key: row.get(key) for key in ("title", "origin", "why_for_you", "strengths_used",
                "family_fit", "constraints_fit", "risks")}
            entry["gaps"] = [{key: gap.get(key) for key in ("need", "have", "gap")} for gap in row["gaps"]]
            trial = row.get("try_it")
            entry["try_it"] = {key: trial.get(key) for key in ("kind", "what", "time_needed")} if isinstance(trial, dict) else None
            entry["favorite"] = row["favorite"]
            entry["focused"] = bool(row["focused_at"])
            entry["facts"] = row.get("facts") or []
            entry["source_labels"] = [{"url": source.get("url"), "label": source.get("status")} for source in row["sources"]]
            compare.append(entry)
        if compare:
            # The Guide prompt's existing <research> grounding rule also covers
            # this nested view of already-published artifacts.
            sections["research"] = sections.get("research", "") + "\n<compare>" + _json(compare) + "</compare>"
    draft = (journey.counselor_summary_draft or {}) if journey else {}
    if decision is not None and not wellbeing and not mirror:
        sections["state"] = _json(guided_state(db, workspace_id, notebook, draft, decision,
            memory.coverage_areas(workspace_id), NotedQuestionService(db).open_requests(workspace_id)))
    sections["journey"] = _json({"stage": journey.current_stage if journey else "IDENTITY",
        "mirror_status": draft.get("status"), "mirror_notebook_version": draft.get("notebook_version")})
    if not wellbeing and not mirror:
        from app.pai_c.deep.actions import workspace_places
        sections["workspace_places"] = _json(workspace_places())
    if mirror:
        from app.workspace_language import workspace_language
        sections["workspace_language"] = _json(workspace_language())
    from app.pai_c.fact_cards import available_cards
    cards = ()
    if decision is not None and decision.question_allowed and not wellbeing and not mirror and decision.action in {"explore_area", "answer_request", "counsel"}:
        cards = tuple(available_cards(snapshot, None if decision.topic == "request" else decision.topic))
        sections["fact_cards"] = _json(cards)
    text = "<context>\n" + "\n".join(
        f"<{name}>{value}</{name}>" for name, value in sections.items()
    ) + "\n</context>"
    counts = {name: estimated_tokens(value) for name, value in sections.items()}
    elapsed = int((time.monotonic() - started) * 1000)
    logger.info("counselor_deep_context tokens=%s total_tokens=%d build_ms=%d",
                counts, estimated_tokens(text), elapsed)
    return DeepContext(text, counts, notebook, journey, elapsed, plan, cards, tuple((research or {}).get("facts", [])))
