"""PAI C facade; shared memory never depends on the Counselor."""

from app.memory.student_snapshot import StudentSnapshotService
from app.memory.episodic import EpisodicMemoryService
from app.memory.permissions import capabilities_for_agent
from app.memory.vault_context import estimated_tokens, select_context_entries  # noqa: F401  re-exported for PAI C
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.turn_input import shared_history


class MemoryService:
    def __init__(self, db):
        self.db = db

    def save_fact_card(self, workspace_id, spec, value, evidence, record_id=None):
        from sqlalchemy import select
        from app.models import MemoryCandidate, Workspace
        from app.memory.candidates import MemoryCandidateService
        from app.memory.reconciler import MemoryReconciler
        self.db.get(Workspace, workspace_id, with_for_update=True)
        previous = self.db.scalar(select(MemoryCandidate).where(
            MemoryCandidate.workspace_id == workspace_id,
            MemoryCandidate.evidence["capture"].as_string() == "fact_card",
            MemoryCandidate.evidence["submission_id"].as_string() == evidence["submission_id"]))
        key = spec.get("record_type") or spec["field_key"]
        if previous:
            if previous.key != key or previous.proposed_value != {"value": value} or (previous.entities or {}).get("record_id") != record_id:
                raise ValueError("Submission id already used for another answer")
            return {"saved": previous.status == "accepted", "candidate_id": previous.id}
        candidate = MemoryCandidateService(self.db).propose(workspace_id,
            candidate_type="student_record" if spec.get("record_type") else "vault_fact",
            key=key, proposed_value=value, entities={"record_id": record_id} if record_id else {},
            source_type="user_explicit", allow_user_explicit=True, confidence=1,
            input_channel="profile", evidence=evidence)
        result = MemoryReconciler(self.db).reconcile(candidate)
        return {"saved": result.accepted, "id": result.result_id, "candidate_id": candidate.id}

    def profile_cards(self, workspace_id):
        from app.memory.student_profile_view import StudentProfileView, PROFILE_SECTIONS
        from app.memory.student_records import StudentRecordService
        from app.memory.evidence import evidence_level, evidence_policy, value_digest
        snapshot = self.profile(workspace_id)
        safe = StudentProfileView(self.db).safe_facts(workspace_id)
        cards = []
        def append(kind, key, row, value):
            evidence = row.get("evidence") or {}
            cards.append({"kind": kind, "key": key, "id": row["id"], "value": value,
                "digest": value_digest(value), "evidence_level": evidence_level(row, value),
                "source": {name: evidence[name] for name in evidence_policy()["source_fields"] if name in evidence},
                "source_type": row.get("source_type"),
                "updated_at": row.get("updated_at") or row.get("valid_from")})
        for key in safe:
            if key in snapshot.facts:
                append("vault_fact", key, snapshot.facts[key], snapshot.facts[key]["value"])
        records = StudentRecordService(self.db)
        for kind in dict.fromkeys(kind for _, kinds in PROFILE_SECTIONS for kind in kinds):
            metadata = {row["id"]: row for row in snapshot.records.get(kind, [])}
            for row in records.list(workspace_id, kind):
                append(kind, kind, metadata[row.id], records._values(kind, row))
        return cards

    def review_profile_card(self, workspace_id, kind, record_id, review):
        import json
        from datetime import datetime, timezone
        from sqlalchemy import select
        from app.models import MemoryCandidate, Workspace
        from app.memory.candidates import MemoryCandidateService
        from app.memory.reconciler import MemoryReconciler
        from app.memory.evidence import value_digest
        self.db.get(Workspace, workspace_id, with_for_update=True)
        prior = self.db.scalar(select(MemoryCandidate).where(
            MemoryCandidate.workspace_id == workspace_id,
            MemoryCandidate.evidence["capture"].as_string() == "profile_review",
            MemoryCandidate.evidence["submission_id"].as_string() == str(review.submission_id)))
        request = {"kind": kind, "id": record_id, "action": review.action,
                   "digest": review.expected_digest, "value": review.value, "text": review.text}
        if prior:
            if (prior.evidence or {}).get("request_digest") != value_digest(request):
                raise ValueError("Submission id already used for another review")
            return {"saved": prior.status == "accepted", "candidate_id": prior.id}
        card = next((row for row in self.profile_cards(workspace_id) if row["kind"] == kind and row["id"] == record_id), None)
        if card is None or card["digest"] != review.expected_digest:
            raise ValueError("This fact changed. Reload it before reviewing")
        value = card["value"] if review.action in {"confirm", "remove"} else review.value
        if value is None or (review.action == "edit" and not review.text.strip()):
            raise ValueError("An edited value and your explanation are required")
        evidence = {"capture": "profile_review", "action": review.action,
            "submission_id": str(review.submission_id), "request_digest": value_digest(request),
            "quote": review.text.strip() or json.dumps(value, ensure_ascii=False, default=str),
            "previous_source": card["source"], "semantic_correction": review.action == "edit"}
        if review.action == "confirm":
            evidence["confirmation"] = {"value_digest": card["digest"],
                "confirmed_at": datetime.now(timezone.utc).isoformat()}
        candidate = MemoryCandidateService(self.db).propose(workspace_id,
            candidate_type="vault_fact" if kind == "vault_fact" else "student_record",
            key=card["key"], proposed_value=value, operation="retract" if review.action == "remove" else "upsert",
            entities={"record_id": record_id} if kind != "vault_fact" else {},
            source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            confidence=1, evidence=evidence)
        result = MemoryReconciler(self.db).reconcile(candidate)
        return {"saved": result.accepted, "id": result.result_id, "candidate_id": candidate.id}

    def recent_turns(self, turn, owner_id, *, limit=24):
        return shared_history(self.db, turn, owner_id, limit=limit)

    def profile(self, workspace_id):
        return StudentSnapshotService(self.db).build(workspace_id)

    def comparable_facts(self, workspace_id):
        from app.memory.student_schema import RECORD_SPECS
        snapshot = self.profile(workspace_id)
        facts = {key: row for key, row in snapshot.facts.items() if row.get("evidence_level") in {"shown", "confirmed"}}
        for kind, rows in snapshot.records.items():
            spec = RECORD_SPECS.get(kind, {})
            for row in rows:
                if row.get("evidence_level") not in {"shown", "confirmed"}:
                    continue
                identity = ",".join(str(row.get(key) or "") for key in spec.get("identity", []))
                for key, value in row.items():
                    if key in spec.get("identity", []) or not isinstance(value, (str, int, float)):
                        continue
                    facts[f"{kind}[{identity}].{key}"] = {"value": value, "evidence_level": row["evidence_level"]}
        return facts

    def truth_map(self, workspace_id):
        return NotebookService(self.db).get(workspace_id)

    def counselor_vault(self, workspace_id, student_text, *, exclude_types=()):
        """The Vault as the counselor may see it (VAULT_SPEC Access): the entries
        relevant to this turn, sensitive only when the turn needs them,
        restricted never, and no evidence, so never the student's original words."""
        from app.memory.vault_context import context_entry, context_policy, counselor_view, view_entries
        view = counselor_view(self.db, workspace_id, student_text)
        entries = [context_entry(entry) for entry in select_context_entries(
            view, student_text, budget_tokens=context_policy()["counselor_budget_tokens"])
            if entry["type"] not in exclude_types]
        chosen = {entry["id"] for entry in entries}
        marked = [entry for entry in view_entries(view) if entry["id"] in chosen]
        return {"entries": entries,
                "needs_recheck": [{"id": e["id"], "label": e["label"]} for e in marked if e["stale"]],
                "in_question": [{"id": e["id"], "label": e["label"]} for e in marked if e["in_question"]],
                "open_profile_issues": [{"type": card["type"], "question": card["question"]}
                                        for card in view["conflicts"][:5]]}

    def is_restricted(self, type_key):
        from app.memory.catalog import vault_catalog
        spec = vault_catalog().type(type_key)
        return spec is not None and spec.sensitivity == "restricted"

    def coverage_areas(self, workspace_id):
        from app.pai_c.understanding.views import coverage_areas
        from app.memory.vault_items import VaultItemService
        return coverage_areas(self.truth_map(workspace_id).notebook, self.profile(workspace_id),
                              VaultItemService(self.db).active(workspace_id))

    def academic_view(self, workspace_id):
        from app.pai_c.understanding.views import academic_view
        return academic_view(self.truth_map(workspace_id).notebook, self.profile(workspace_id))

    def personal_view(self, workspace_id):
        from app.pai_c.understanding.views import personal_view
        return personal_view(self.truth_map(workspace_id).notebook)

    def profile_sections(self, workspace_id):
        from app.pai_c.understanding.views import profile_sections
        return profile_sections(self.truth_map(workspace_id).notebook)

    def capability_view(self, workspace_id):
        from app.pai_c.understanding.views import capability_view
        return capability_view(self.truth_map(workspace_id).notebook)

    def latest_plan(self, workspace_id):
        from sqlalchemy import select, func, or_, and_
        from app.config import config
        from app.models import PaiTurnPlan, EventRecord, Workspace
        from app.pai_c.planner.plan import validate_plan
        workspace = self.db.get(Workspace, workspace_id)
        if workspace is None or workspace.status != "active":
            return None
        rows = self.db.scalars(select(PaiTurnPlan).join(EventRecord, PaiTurnPlan.source_event_id == EventRecord.id).where(
            PaiTurnPlan.workspace_id == workspace_id, EventRecord.network_id == workspace_id
        ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc()).limit(1)).all()
        for row in rows:
            event = self.db.get(EventRecord, row.source_event_id)
            later = self.db.scalar(select(func.count()).select_from(EventRecord).where(
                EventRecord.network_id == workspace_id,
                EventRecord.type == "workspace.message.posted",
                EventRecord.source.like("human:%"),
                or_(EventRecord.timestamp > event.timestamp,
                    and_(EventRecord.timestamp == event.timestamp, EventRecord.id > event.id)),
            ))
            if later > config.PAI_PLAN_MAX_AGE_TURNS:
                return None
            try:
                return validate_plan(row.plan)
            except ValueError:
                continue
        return None


    def agent_capabilities(self, agent_name):
        return capabilities_for_agent(agent_name)

    def patch_applied_since(self, workspace_id, event_id):
        """Accepted map history, including a patch for the edit itself.

        A rejected Planner patch never creates history. The pre-Mirror sensitive
        check reuses the existing source event, so cannot advance this boundary.
        """
        from sqlalchemy import select, or_, and_
        from app.models import CounselorNotebookHistory, EventRecord
        boundary = self.db.scalar(select(EventRecord).where(
            EventRecord.network_id == workspace_id, EventRecord.id == event_id))
        if boundary is None:
            return False
        return self.db.scalar(select(CounselorNotebookHistory.id).join(
            EventRecord, EventRecord.id == CounselorNotebookHistory.source_event_id).where(
                CounselorNotebookHistory.workspace_id == workspace_id,
                EventRecord.network_id == workspace_id,
                EventRecord.source.like("human:%"),
                or_(EventRecord.timestamp > boundary.timestamp,
                    and_(EventRecord.timestamp == boundary.timestamp, EventRecord.id >= boundary.id)),
            ).limit(1)) is not None

    def apply_truth_map(self, workspace_id, new_notebook, source_event_id, *, expected_version=None):
        return NotebookService(self.db).apply(
            workspace_id, new_notebook, source_event_id, expected_version=expected_version)

    def enqueue_turn_extraction(self, **kwargs):
        # Preserve the existing validated candidate/reconciliation write path.
        from app.memory.turn_hook import enqueue_turn_extraction
        return enqueue_turn_extraction(db=self.db, **kwargs)

    def understanding_summary(self, workspace_id):
        notebook = self.truth_map(workspace_id).notebook.model_dump(mode="json")
        return {key: notebook[key] for key in ("said", "source", "pressures", "self", "sure")}

    def foundation_ready(self, truth_map):
        from app.pai_c.deep.coverage import foundation_ready
        return foundation_ready(truth_map)

    def delete_for_workspace(self, workspace_id):
        from sqlalchemy import delete
        from app.models import PaiTurnPlan, CounselorMirrorFeedback
        self.db.execute(delete(PaiTurnPlan).where(PaiTurnPlan.workspace_id == workspace_id))
        self.db.execute(delete(CounselorMirrorFeedback).where(CounselorMirrorFeedback.workspace_id == workspace_id))
        return NotebookService(self.db).delete_for_workspace(workspace_id)

    def export_truth_map(self, workspace_id):
        from sqlalchemy import select
        from app.models import CounselorNotebook, CounselorNotebookHistory
        from app.pai_c.deep.notebook_schema import CounselorNotebookData
        def export_row(row):
            data = {column.key: getattr(row, column.key) for column in row.__table__.columns}
            data["notebook"] = CounselorNotebookData.model_validate(row.notebook).export_data()
            return data
        latest = self.db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace_id))
        history = self.db.scalars(select(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == workspace_id).order_by(CounselorNotebookHistory.version)).all()
        return {"latest": export_row(latest) if latest else None, "history": [export_row(row) for row in history]}

    def session_turns(self, workspace_id):
        from sqlalchemy import select
        from app.models import EventRecord, Workspace
        workspace = self.db.get(Workspace, workspace_id)
        if workspace is None:
            return []
        rows = self.db.scalars(select(EventRecord).where(
            EventRecord.network_id == workspace_id,
            EventRecord.type == "workspace.message.posted",
            EventRecord.source.in_((f"human:{workspace.owner_user_id}", "openagents:pai")),
        ).order_by(EventRecord.timestamp, EventRecord.id)).all()
        return [{"id": row.id, "timestamp": row.timestamp,
                 "role": "student" if row.source.startswith("human:") else "counselor",
                 "content": row.payload["content"]}
                for row in rows if isinstance((row.payload or {}).get("content"), str)
                and row.payload["content"].strip()
                and (row.payload or {}).get("message_type", "chat") in
                    ("chat", "counselor_mirror", "operator_result")]

    def ended_sessions(self, now_ms):
        from sqlalchemy import select
        from app.config import config
        from app.models import Workspace
        gap = max(1, config.PAI_SESSION_GAP_MINUTES) * 60_000
        ended = []
        for workspace_id in self.db.scalars(select(Workspace.id)):
            turns = self.session_turns(workspace_id)
            groups = []
            last_student = None
            for turn in turns:
                if turn["role"] == "student":
                    if last_student is None or turn["timestamp"] - last_student > gap:
                        groups.append([])
                    last_student = turn["timestamp"]
                if groups:
                    groups[-1].append(turn)
            covered = {event_id for row in self.session_summaries(workspace_id, limit=None)
                       for event_id in row.source_event_ids or []}
            for group in groups:
                students = [row for row in group if row["role"] == "student"]
                first, last = students[0], students[-1]
                if now_ms - last["timestamp"] > gap and last["id"] not in covered:
                    ended.append({"workspace_id": workspace_id,
                                  "first_event_id": first["id"], "last_event_id": last["id"]})
        return ended

    def session_summaries(self, workspace_id, limit=2):
        return EpisodicMemoryService(self.db).recent(
            workspace_id, limit=limit, event_type="session_summary")

    def is_return_visit(self, workspace_id):
        from sqlalchemy import select, func
        from app.config import config
        from app.models import EventRecord, Workspace
        workspace = self.db.get(Workspace, workspace_id)
        if workspace is None:
            return False
        content = EventRecord.payload["content"].as_string()
        timestamps = self.db.scalars(select(EventRecord.timestamp).where(
            EventRecord.network_id == workspace_id,
            EventRecord.type == "workspace.message.posted",
            EventRecord.source == f"human:{workspace.owner_user_id}",
            func.trim(content) != "",
            func.coalesce(EventRecord.payload["message_type"].as_string(), "chat") == "chat",
        ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc()).limit(2)).all()
        return (len(timestamps) == 2 and timestamps[0] - timestamps[1]
                > max(1, config.PAI_SESSION_GAP_MINUTES) * 60_000)

    def session_input(self, workspace_id, first_event_id, last_event_id):
        from sqlalchemy import select
        from app.config import config
        from app.models import CounselorNotebookHistory
        from app.pai_c.deep.notebook_schema import CounselorNotebookData
        turns = self.session_turns(workspace_id)
        students = [row for row in turns if row["role"] == "student"]
        by_id = {row["id"]: row for row in students}
        first, last = by_id.get(first_event_id), by_id.get(last_event_id)
        if first is None or last is None or first["timestamp"] > last["timestamp"]:
            raise ValueError("Invalid session boundaries")
        following = next((row for row in students if row["timestamp"] > last["timestamp"]), None)
        upper = following["timestamp"] if following else last["timestamp"] + max(1, config.PAI_SESSION_GAP_MINUTES) * 60_000
        selected = [row for row in turns if first["timestamp"] <= row["timestamp"] < upper]
        ids = {row["id"] for row in selected}
        history = self.db.scalars(select(CounselorNotebookHistory).where(
            CounselorNotebookHistory.workspace_id == workspace_id
        ).order_by(CounselorNotebookHistory.version)).all()
        previous = CounselorNotebookData().model_dump(mode="json")
        changes = []
        for version in history:
            current = CounselorNotebookData.model_validate(version.notebook).model_dump(mode="json")
            if version.source_event_id in ids:
                for key in current:
                    if previous.get(key) != current[key]:
                        changes.append({"version": version.version, "field": key,
                                        "before": previous.get(key), "after": current[key]})
            previous = current
        return {"turns": selected, "truth_map_changes": changes}

    def record_session_summary(self, workspace_id, data, turns):
        from datetime import datetime, timezone
        last_id = next(row["id"] for row in reversed(turns) if row["role"] == "student")
        for episode in self.session_summaries(workspace_id, limit=None):
            if last_id in (episode.source_event_ids or []):
                return episode
        # Session-specific fingerprint prevents equal summaries collapsing distinct sessions.
        from app.memory.dedupe import episode_fingerprint
        from app.models import PaiEpisode, Workspace
        self.db.get(Workspace, workspace_id, with_for_update=True)
        for episode in self.session_summaries(workspace_id, limit=None):
            if last_id in (episode.source_event_ids or []):
                return episode
        summary = "; ".join(data["discussed"]) or "Session completed."
        row = PaiEpisode(workspace_id=workspace_id, event_type="session_summary",
            summary=summary[:1000], entities=data, importance=0.5, status="active",
            occurred_at=datetime.fromtimestamp(turns[-1]["timestamp"] / 1000, timezone.utc),
            source_event_ids=[turn["id"] for turn in turns],
            fingerprint=episode_fingerprint("session_summary", last_id))
        self.db.add(row)
        self.db.flush()
        from app.config import config
        if config.PAI_SEMANTIC_RECALL_ENABLED:
            from app.runtime.task_runtime import enqueue
            enqueue(self.db, job_type="memory.embed", workspace_id=workspace_id,
                    payload={"episode_ids": [row.id]}, idempotency_key=f"embed-session:{last_id}")
        return row

    async def recall(self, workspace_id, query, top_k=None):
        import asyncio
        from app.config import config
        from app.memory.retriever import MemoryRetriever
        from app.memory.student_records import ENTITY_MODELS
        if not config.PAI_SEMANTIC_RECALL_ENABLED:
            return []
        kinds = ("episode", "vault_fact", "document_chunk") + tuple("student_record:" + kind for kind in ENTITY_MODELS)
        retriever = MemoryRetriever(self.db)
        try:
            result = await asyncio.wait_for(retriever.retrieve(workspace_id, query,
                kinds=kinds, event_types=("session_summary",),
                limit=top_k or config.PAI_SEMANTIC_RECALL_TOP_K),
                timeout=max(0.05, config.PAI_MEMORY_CONTEXT_TIMEOUT_MS / 1000))
        except (TimeoutError, RuntimeError):
            result = retriever._fallback(workspace_id, query, kinds, None,
                top_k or config.PAI_SEMANTIC_RECALL_TOP_K, ("session_summary",))
        return [{"id": item.id, "kind": item.kind, "text": item.text} for item in result.ordered]
