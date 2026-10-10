"""Versioned roadmap content and isolated student actions."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from copy import deepcopy
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select, update

from app.models import DecisionRecord, ExecutionRun, Opportunity, RequirementSet, Roadmap, RoadmapStudentState, StudentJourney
from app.plugins._shared.sources import public_https


class RoadmapError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


class RoadmapService:
    def __init__(self, db):
        self.db = db

    def _require(self, workspace_id: str, roadmap_id: str, *, lock=False) -> tuple[Roadmap, RoadmapStudentState]:
        query = select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id, Roadmap.id == roadmap_id)
        if lock:
            query = query.with_for_update()
        pair = self.db.execute(query).one_or_none()
        if pair is None:
            raise RoadmapError("Roadmap not found")
        return pair

    def list(self, workspace_id: str, filter_by: str = "all", *, presented=False) -> list[dict]:
        if filter_by not in {"all", "favorites", "exploring", "dismissed"}:
            raise RoadmapError("Invalid roadmap filter")
        pairs = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id).order_by(Roadmap.created_at.desc())).all()
        now = _now()
        rows = []
        for roadmap, state in pairs:
            if filter_by == "dismissed":
                if state.dismissed_at is None:
                    continue
            elif state.dismissed_at is not None:
                continue
            if filter_by == "favorites" and not state.favorite:
                continue
            if filter_by == "exploring" and not state.exploring:
                continue
            newly_presented = state.presented_at is None
            if presented and newly_presented:
                state.presented_at = now
            rows.append(self.serialize(roadmap, state) | {"new": newly_presented})
        rows.sort(key=lambda item: (
            0 if item["chosen_at"] else 1,
            0 if item["favorite"] else 1,
            0 if item["origin"] == "stated_goal" else 1,
        ))
        return rows

    def get(self, workspace_id: str, roadmap_id: str, *, presented=False) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id)
        if presented and state.presented_at is None:
            state.presented_at = _now()
        return self.serialize(roadmap, state)

    def get_detail(self, workspace_id: str, roadmap_id: str, *, presented=False) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id)
        if presented and state.presented_at is None:
            state.presented_at = _now()
        result = self.serialize(roadmap, state)
        evidence = (self.db.execute(select(RequirementSet).join(Opportunity).where(
            RequirementSet.id == roadmap.requirement_set_id,
            Opportunity.workspace_id == workspace_id)).scalar_one_or_none()
            if roadmap.requirement_set_id else None)
        if evidence:
            result["evidence"] = {
                "id": evidence.id, "status": evidence.status, "version": evidence.version,
                "rules": evidence.rules, "fees": evidence.fees,
                "deadlines": evidence.deadlines,
                "verification_checks": evidence.verification_checks,
                "source_url": evidence.source_url,
                "checked_at": evidence.checked_at.isoformat(),
            }
            versions = self.db.execute(select(RequirementSet).where(
                RequirementSet.opportunity_id == evidence.opportunity_id,
            ).order_by(RequirementSet.version.desc())).scalars().all()
            result["evidence_history"] = [{"version": row.version, "status": row.status,
                                          "checked_at": row.checked_at.isoformat(),
                                          "source_url": row.source_url} for row in versions]
        else:
            result["evidence"] = None
            result["evidence_history"] = []
        return result

    def prepare_retry(self, workspace_id: str, roadmap_id: str) -> tuple[str, dict]:
        """Retry the prior research brief while keeping this card and its state."""
        roadmap, _ = self._require(workspace_id, roadmap_id, lock=True)
        from app.research.gateway import mirror_is_current
        if not mirror_is_current(self.db, workspace_id):
            raise RoadmapError("Confirm your current Mirror before retrying research")
        if roadmap.generation_status not in {"failed", "stale", "needs_info"}:
            raise RoadmapError("Only failed or stale or incomplete research can be retried")
        previous = self.db.get(ExecutionRun, roadmap.execution_run_id) if roadmap.execution_run_id else None
        if previous is None and roadmap.origin == "student_added":
            constraints = {"capability_input": {"brief": {}}}
            objective = roadmap.title
        elif (previous is None or previous.workspace_id != workspace_id
                or previous.task_type != "roadmap_research"):
            raise RoadmapError("Previous research brief is unavailable")
        else:
            constraints = deepcopy(previous.constraints or {})
            objective = previous.objective
        capability_input = constraints.get("capability_input") or {}
        brief = capability_input.get("brief")
        if not isinstance(brief, dict):
            raise RoadmapError("Previous research brief is unavailable")
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == roadmap.journey_id,
            StudentJourney.workspace_id == workspace_id)).scalar_one_or_none()
        if journey is None or journey.current_stage not in {"PROPOSED", "DIRECTION", "RESEARCHING", "CHOSEN"}:
            raise RoadmapError("Counselor is not ready to retry this route")
        constraints["research_key"] = f"{roadmap.journey_id}:retry:{uuid4()}"
        if roadmap.origin == "student_added":
            constraints["roadmap_id"] = roadmap.id
        else:
            constraints.pop("roadmap_id", None)
            url = (roadmap.route or {}).get("url")
            if public_https(url):
                brief["refresh_candidate"] = {
                      "lane": roadmap.lane,
                    "url": url, "title": roadmap.title, "origin": roadmap.origin,
                    "country": (roadmap.route or {}).get("country"),
                    "level": (roadmap.route or {}).get("level"),
                    "intake": (roadmap.route or {}).get("intake")}
        roadmap.generation_status = "generating"
        roadmap.stale_reason = None
        roadmap.updated_at = _now()
        if journey.current_stage in {"PROPOSED", "DIRECTION"}:
            from app.journey import JourneyService
            JourneyService(self.db).set_counselor_stage(
                workspace_id, journey.id, "RESEARCHING", actor="human:student")
        self.db.flush()
        return objective, constraints

    def for_run(self, workspace_id: str, run_id: str, *, presented=False) -> list[dict]:
        pairs = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id,
            Roadmap.execution_run_id == run_id,
        ).order_by(Roadmap.created_at.asc())).all()
        if presented:
            for _, state in pairs:
                if state.presented_at is None:
                    state.presented_at = _now()
        return [self.serialize(*pair) for pair in pairs]

    @staticmethod
    def serialize(roadmap: Roadmap, state: RoadmapStudentState) -> dict:
        return {key: getattr(roadmap, key) for key in (
            "id", "workspace_id", "journey_id", "goal_id", "origin", "title", "route", "lane",
            "fit_level", "fit_dimensions", "gaps", "steps", "total_cost", "time_to_start",
            "risks", "sources", "generation_status", "execution_run_id", "version",
            "scholarships",
            "stale_reason",
            "requirement_set_id",
        )} | ((roadmap.route or {}).get("counselor_fit") or {}) | {"gap": roadmap.gaps} | {
            "favorite": state.favorite, "exploring": state.exploring,
            "dismissed_at": state.dismissed_at.isoformat() if state.dismissed_at else None,
            "chosen_at": state.chosen_at.isoformat() if state.chosen_at else None,
            "focused_at": state.focused_at.isoformat() if state.focused_at else None,
            "created_at": roadmap.created_at.isoformat() if roadmap.created_at else None,
            "updated_at": roadmap.updated_at.isoformat() if roadmap.updated_at else None,
        }

    def publish_from_run(self, run: ExecutionRun) -> list[str]:
        """Only the registered builder calls this from its status hook."""
        if run.task_type != "roadmap_research":
            raise RoadmapError("Run does not own roadmap research")
        artifact = ((run.result or {}).get("capability_result") or {})
        if not artifact.get("mirror_version") and (run.constraints or {}).get("mirror_version"):
            brief = ((run.constraints or {}).get("capability_input") or {}).get("brief") or {}
            artifact = {"mirror_version": run.constraints["mirror_version"], "roadmaps": [],
                "light_research": {"lanes": [], "decisive_fields": brief.get("decisive_fields") or []}}
        if artifact.get("mirror_version") is not None:
            return self._publish_mirror_run(run, artifact)
        candidates = artifact.get("roadmaps") or []
        journey_id = str((run.constraints or {}).get("research_key") or "").split(":", 1)[0]
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == journey_id,
            StudentJourney.workspace_id == run.workspace_id,
            StudentJourney.journey_type == "counselor_decision",
        )).scalar_one_or_none()
        if journey is None:
            raise RoadmapError("Counselor journey not found for research run")
        custom_id = (run.constraints or {}).get("roadmap_id")
        changed = []
        for position, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or not candidate.get("title"):
                continue
            sources = candidate.get("sources") or []
            if not sources or any(not isinstance(item, dict) or not public_https(item.get("url"))
                                  or not item.get("checked_at") for item in sources):
                continue
            for gap in candidate.get("gaps") or []:
                if not isinstance(gap, dict) or not public_https(gap.get("source_url")):
                    raise RoadmapError("Each published gap needs a source URL")
            origin = candidate.get("origin")
            if origin not in {"stated_goal", "alternative", "family_wish"}:
                continue
            requirement_id = candidate.get("requirement_set_id")
            if requirement_id and not self.db.execute(select(RequirementSet.id).join(Opportunity).where(
                RequirementSet.id == requirement_id,
                Opportunity.workspace_id == run.workspace_id)).first():
                raise RoadmapError("Roadmap evidence does not belong to this student")
            if custom_id and position == 0:
                roadmap = self.db.get(Roadmap, custom_id)
                if roadmap is None or roadmap.workspace_id != run.workspace_id:
                    raise RoadmapError("Custom roadmap placeholder missing")
                origin = "student_added"
            else:
                route_key = json.dumps(candidate.get("route") or {}, sort_keys=True, default=str)
                roadmap_id = str(uuid5(NAMESPACE_URL, f"pai-roadmap:{journey_id}:{origin}:{route_key}"))
                roadmap = self.db.get(Roadmap, roadmap_id)
                if roadmap is None:
                    roadmap = Roadmap(id=roadmap_id, workspace_id=run.workspace_id,
                                      journey_id=journey_id, goal_id=((run.constraints or {}).get("capability_input") or {}).get("brief", {}).get("goal_id"),
                                      origin=origin, title=candidate["title"], execution_run_id=run.id)
                    self.db.add(roadmap)
                    self.db.add(RoadmapStudentState(roadmap_id=roadmap_id, journey_id=journey_id))
            previous_status = roadmap.generation_status
            next_status = "ready" if run.status == "completed" else "needs_info"
            content = {
                "title": candidate["title"], "route": candidate.get("route") or {},
                "fit_level": candidate.get("fit_level") or "unconfirmed",
                "fit_dimensions": candidate.get("fit_dimensions") or {},
                "gaps": candidate.get("gaps") or [], "steps": candidate.get("steps") or [],
                "total_cost": candidate.get("total_cost"),
                "time_to_start": candidate.get("time_to_start"),
                "risks": candidate.get("risks") or [], "sources": sources,
                "scholarships": candidate.get("scholarships") or [],
                "generation_status": next_status,
                "stale_reason": None,
                "requirement_set_id": requirement_id,
            }
            changed_content = any(getattr(roadmap, key) != value for key, value in content.items())
            for key, value in content.items():
                setattr(roadmap, key, value)
            roadmap.execution_run_id = run.id
            if changed_content:
                roadmap.version = (roadmap.version or 1) + (1 if roadmap.created_at else 0)
                roadmap.updated_at = _now()
            changed.append(roadmap.id)
            if next_status == "ready" and previous_status != "ready":
                self._notify_ready(run.workspace_id, roadmap,
                                   refreshed=previous_status == "stale")
        if custom_id and custom_id not in changed and run.status in {"failed", "needs_user_action"}:
            placeholder = self.db.get(Roadmap, custom_id)
            if placeholder and placeholder.workspace_id == run.workspace_id:
                placeholder.generation_status = "needs_info" if run.status == "needs_user_action" else "failed"
                changed.append(placeholder.id)
        if not custom_id and not any(isinstance(item, dict) and
                                     item.get("origin") == "stated_goal" for item in candidates):
            brief = ((run.constraints or {}).get("capability_input") or {}).get("brief") or {}
            title = str(brief.get("stated_preference") or "").strip()
            if title:
                roadmap_id = str(uuid5(NAMESPACE_URL,
                                       f"pai-roadmap:{journey_id}:stated_goal:unresolved:{title.casefold()}"))
                card = self.db.get(Roadmap, roadmap_id)
                if card is None:
                    card = Roadmap(id=roadmap_id, workspace_id=run.workspace_id,
                                   journey_id=journey_id, goal_id=brief.get("goal_id"),
                                   origin="stated_goal", title=title,
                                   route={"country": brief.get("country"),
                                          "level": brief.get("level")},
                                   generation_status="failed")
                    self.db.add(card)
                    self.db.add(RoadmapStudentState(roadmap_id=roadmap_id,
                                                    journey_id=journey_id))
                card.execution_run_id = run.id
                card.generation_status = "needs_info" if run.status == "needs_user_action" else "failed"
                reasons = artifact.get("unconfirmed") or []
                card.stale_reason = next((str(item.get("reason")) for item in reasons
                                          if isinstance(item, dict) and item.get("reason")),
                                         "PAI could not confirm a programme for this direction yet")
                card.updated_at = _now()
                changed.append(card.id)
        self.db.flush()
        return changed

    def _publish_mirror_run(self, run, artifact):
        from app.config import config
        from app.pai_c.deep.polish import contains_blocked_script
        from app.research.requirements import RequirementStore
        from app.research.gateway import mirror_is_current
        from app.models import CounselorNotedQuestion
        from app.pai_c.deep.roadmaps import FIT_FIELDS, fact_index, ground_roadmap, lanes_for_mirror

        version = artifact["mirror_version"]
        if (run.constraints or {}).get("mirror_version") != version:
            return []
        if not mirror_is_current(self.db, run.workspace_id, version):
            return []
        journey_id = (run.constraints or {}).get("research_key", "").split(":", 1)[0]
        journey = self.db.scalar(select(StudentJourney).where(StudentJourney.id == journey_id,
            StudentJourney.workspace_id == run.workspace_id, StudentJourney.status == "active"))
        if journey is None or (journey.counselor_summary_draft or {}).get("version") != version:
            return []
        brief = ((run.constraints or {}).get("capability_input") or {}).get("brief") or {}
        research = artifact.get("light_research") or {}
        facts = fact_index(research)
        # Reject forged fact IDs: provenance must exist in this workspace's
        # evidence store. The public cache materializes an isolated local copy.
        for key, fact in list(facts.items()):
            row = self.db.scalar(select(RequirementSet).join(Opportunity).where(
                RequirementSet.id == fact.get("requirement_set_id"), Opportunity.workspace_id == run.workspace_id))
            stored = RequirementStore.payload(self.db.get(Opportunity, row.opportunity_id), row) if row else {}
            candidates = [*(stored.get("rules") or []), *(stored.get("fees") or {}).values(),
                          *(stored.get("deadlines") or {}).values()]
            match = next((item for item in candidates if item["fact_id"] == key and
                         item.get("quote") == fact.get("quote") and item.get("source_url") == fact.get("source_url")), None)
            if match is None: facts.pop(key)
            else:
                fact.update(match)
                fact["label"] = row.status if RequirementStore.is_fresh(row) else "unconfirmed"
        research = {**research, "lanes": [{**lane, "facts": [facts[item["fact_id"]]
            for item in lane.get("facts") or [] if item.get("fact_id") in facts]}
            for lane in research.get("lanes") or []]}
        changed = []
        answers = {item["question_id"]: item for item in artifact.get("question_answers") or []
                   if isinstance(item, dict) and item.get("question_id") and item.get("fact_id") in facts
                     and facts[item["fact_id"]].get("label") == "verified"
                     and not contains_blocked_script(facts[item["fact_id"]]["quote"], config.PAI_LANGUAGE_BLOCKED_SCRIPTS)}
        previous_answers = []
        requested_ids = {item["id"] for item in brief.get("questions") or []}
        for question in self.db.scalars(select(CounselorNotedQuestion).where(
                CounselorNotedQuestion.workspace_id == run.workspace_id,
                CounselorNotedQuestion.status == "answered")):
            if question.id in requested_ids:
                continue
            evidence = self.db.scalar(select(RequirementSet).join(Opportunity).where(
                RequirementSet.id == (question.fact_id or "").split(":", 1)[0],
                Opportunity.workspace_id == run.workspace_id))
            valid = bool(evidence and evidence.status == "verified" and RequirementStore.is_fresh(evidence)
                and not contains_blocked_script((question.answer or {}).get("text", ""), config.PAI_LANGUAGE_BLOCKED_SCRIPTS))
            if not valid:
                question.status = "unanswered"
            answer = question.answer or {}
            previous_answers.append({"id": question.id, "question": question.question_to_research,
                "status": "answered" if valid else "unanswered", "answer": answer.get("text") if valid else None,
                "source_url": answer.get("source_url") if valid else None,
                "label": "verified" if valid else "unconfirmed"})
        by_lane = {item.get("lane"): item for item in artifact.get("roadmaps") or [] if isinstance(item, dict)}
        custom_id = (run.constraints or {}).get("roadmap_id")
        lanes = ([{"lane": "student_added", "why": (brief.get("custom_roadmap") or {}).get("title", "")}]
                 if custom_id else lanes_for_mirror(brief.get("mirror") or {}))
        for lane in lanes:
            candidate = by_lane.get(lane["lane"], {})
            # Revalidate at publication, not only at generation. Translate the
            # generated artifact back to its input contract without trusting status.
            candidate = {**candidate, "status": candidate.get("generation_status"),
                         "gap": candidate.get("gap") or []}
            item = ground_roadmap(candidate, lane, facts, research,
                {key: brief.get(key) or {} for key in ("notebook", "profile", "mirror")})
            # A useful cited route can be ready even if the overall research run
            # needs more input for a different route or an unanswered question.
            roadmap_id = custom_id or str(uuid5(NAMESPACE_URL, f"pai-mirror-roadmap:{journey_id}:{lane['lane']}"))
            roadmap = self.db.get(Roadmap, roadmap_id)
            if roadmap is not None and (roadmap.workspace_id != run.workspace_id or roadmap.journey_id != journey_id):
                raise RoadmapError("Roadmap does not belong to this journey")
            if roadmap is None:
                roadmap = Roadmap(id=roadmap_id, workspace_id=run.workspace_id, journey_id=journey_id,
                    lane=lane["lane"], origin=item["origin"], title=item["title"], version=1)
                self.db.add(roadmap); self.db.flush()
                self.db.add(RoadmapStudentState(roadmap_id=roadmap_id, journey_id=journey_id))
            elif roadmap.execution_run_id != run.id:
                roadmap.version += 1
            fit = {key: item.get(key) for key in FIT_FIELDS}
            if custom_id: fit["lane"] = "student_added"
            fit.update(missing_facts=item["missing_facts"], mirror_version=version,
                       facts=item.get("facts") or [], citations=item.get("citations") or {})
            fit["your_questions"] = [{"id": question["id"], "question": question["question"],
                "status": "answered" if question["id"] in answers else "unanswered",
                "answer": facts[answers[question["id"]]["fact_id"]]["quote"] if question["id"] in answers else None,
                "source_url": facts[answers[question["id"]]["fact_id"]]["source_url"] if question["id"] in answers else None,
                "label": facts[answers[question["id"]]["fact_id"]]["label"] if question["id"] in answers else None}
                for question in brief.get("questions") or []] + previous_answers
            previous_status = roadmap.generation_status
            roadmap.route = {**item["route"], "counselor_fit": fit}
            roadmap.title = item["title"]; roadmap.gaps = item["gap"]
            roadmap.steps = item["steps"]; roadmap.risks = item["risks"]
            roadmap.sources = item["sources"]; roadmap.generation_status = item["generation_status"]
            roadmap.requirement_set_id = item["requirement_set_id"]
            roadmap.execution_run_id = run.id; roadmap.updated_at = _now(); roadmap.stale_reason = None
            if item["generation_status"] == "ready" and previous_status != "ready":
                self._notify_ready(run.workspace_id, roadmap, refreshed=previous_status == "stale")
            changed.append(roadmap.id)
        for question in brief.get("questions") or []:
            row = self.db.scalar(select(CounselorNotedQuestion).where(
                CounselorNotedQuestion.id == question["id"], CounselorNotedQuestion.workspace_id == run.workspace_id))
            if not row: continue
            answer = answers.get(row.id)
            fact = facts.get(answer["fact_id"]) if answer else None
            if fact and fact.get("label") == "verified":
                row.status = "answered"; row.fact_id = fact["fact_id"]
                row.answer = {"text": fact["quote"], "source_url": fact["source_url"], "label": fact["label"]}
            elif row.status != "answered":
                row.status = "unanswered"
        self.db.flush()
        return changed

    def mark_stale(self, workspace_id: str, reason: str, *, source_url: str | None = None) -> int:
        """Invalidate old fit without replacing a student's choices or annotations."""
        rows = self.db.execute(select(Roadmap).where(
            Roadmap.workspace_id == workspace_id,
            Roadmap.generation_status.in_(("ready", "needs_info")),
        )).scalars().all()
        affected = 0
        for row in rows:
            if source_url and not any(item.get("url") == source_url for item in row.sources or []):
                continue
            row.generation_status = "stale"
            row.stale_reason = reason[:240]
            row.updated_at = _now()
            from app.services.notify import notify_once
            notify_once(self.db, workspace_id, dedupe_key=f"roadmap-stale:{row.id}:{row.version}",
                        source="system:roadmaps", title="Roadmap needs a fresh check",
                        message=row.title, link_url="/roadmaps")
            affected += 1
        return affected

    def _notify_ready(self, workspace_id: str, roadmap: Roadmap, *, refreshed: bool = False):
        from app.services.notify import notify_once
        key = f"roadmap-ready:{roadmap.id}:{roadmap.version}"
        notify_once(self.db, workspace_id, source="system:roadmaps",
                    title="Roadmap refreshed" if refreshed else "A roadmap is ready",
                    message=roadmap.title, link_url="/roadmaps", dedupe_key=key)

    def set_flag(self, workspace_id: str, roadmap_id: str, field: str, value: bool) -> dict:
        if field not in {"favorite", "exploring"}:
            raise RoadmapError("Unknown student action")
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        setattr(state, field, bool(value))
        self.db.flush()
        return self.serialize(roadmap, state)

    def dismiss(self, workspace_id: str, roadmap_id: str, dismissed: bool) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        if state.chosen_at and dismissed:
            raise RoadmapError("Chosen roadmap cannot be dismissed")
        state.dismissed_at = _now() if dismissed else None
        if dismissed:
            state.focused_at = None
        self.db.flush()
        return self.serialize(roadmap, state)

    def create_custom(self, workspace_id: str, journey_id: str, goal_id: str,
                      title: str, route: dict) -> dict:
        existing = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id,
            Roadmap.journey_id == journey_id,
            Roadmap.goal_id == goal_id,
            Roadmap.origin == "student_added",
        ).limit(1)).one_or_none()
        if existing:
            return self.serialize(*existing)
        roadmap = Roadmap(workspace_id=workspace_id, journey_id=journey_id,
                          goal_id=goal_id, origin="student_added", title=title,
                          route=route, generation_status="generating")
        self.db.add(roadmap)
        self.db.flush()
        state = RoadmapStudentState(roadmap_id=roadmap.id, journey_id=journey_id)
        self.db.add(state)
        self.db.flush()
        return self.serialize(roadmap, state)

    def focus(self, workspace_id: str, roadmap_id: str) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        if state.dismissed_at or roadmap.generation_status not in {"ready", "needs_info", "stale"}:
            raise RoadmapError("Roadmap is unavailable for discussion")
        self.db.execute(update(RoadmapStudentState).where(
            RoadmapStudentState.journey_id == roadmap.journey_id,
            RoadmapStudentState.roadmap_id != roadmap.id,
        ).values(focused_at=None))
        state.focused_at = _now()
        self.db.flush()
        return self.serialize(roadmap, state)

    def rethink(self, workspace_id: str, roadmap_id: str) -> dict:
        """An explicit 'not yet' returns to discovery and keeps the old route."""
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == roadmap.journey_id,
            StudentJourney.workspace_id == workspace_id,
        ).with_for_update()).scalar_one_or_none()
        if journey is None or journey.current_stage != "PROPOSED":
            raise RoadmapError("Only a proposed direction can be reconsidered")
        from app.journey import JourneyService
        JourneyService(self.db).set_counselor_stage(
            workspace_id, journey.id, "DIRECTION", actor="human:student")
        decisions = list(journey.decisions or [])
        decisions.append({"kind": "roadmap_rethink", "roadmap_id": roadmap.id,
                          "at": _now().isoformat()})
        journey.decisions = decisions
        self.db.flush()
        return self.serialize(roadmap, state)

    def focused(self, workspace_id: str) -> dict | None:
        pair = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id,
            RoadmapStudentState.focused_at.isnot(None),
        ).order_by(RoadmapStudentState.focused_at.desc()).limit(1)).one_or_none()
        return self.serialize(*pair) if pair else None

    @staticmethod
    def choice_token(roadmap: Roadmap, workspace_secret: str) -> str:
        expiry = int(time.time()) + 600
        body = f"{roadmap.workspace_id}:{roadmap.id}:{roadmap.version}:{expiry}"
        signature = hmac.new(workspace_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return f"{expiry}.{signature}"

    def choose(self, workspace_id: str, roadmap_id: str, token: str, workspace_secret: str,
               *, choice_channel: str = "roadmaps") -> dict:
        if choice_channel not in {"chat", "voice", "roadmaps"}:
            raise RoadmapError("Invalid choice channel")
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == roadmap.journey_id,
            StudentJourney.workspace_id == workspace_id,
        ).with_for_update()).scalar_one_or_none()
        if journey is None or journey.current_stage != "PROPOSED":
            raise RoadmapError("Counselor has not presented a route for choice")
        if state.presented_at is None or state.dismissed_at or roadmap.generation_status != "ready":
            raise RoadmapError("Only a presented, ready roadmap can be chosen")
        mirror_version = ((roadmap.route or {}).get("counselor_fit") or {}).get("mirror_version")
        if mirror_version is not None:
            from app.research.gateway import mirror_is_current
            if not mirror_is_current(self.db, workspace_id, mirror_version):
                raise RoadmapError("This route needs research for the current Mirror")
        try:
            expiry_text, signature = token.split(".", 1)
            expiry = int(expiry_text)
        except (ValueError, AttributeError):
            raise RoadmapError("Invalid choice confirmation") from None
        if expiry < int(time.time()) or expiry > int(time.time()) + 600:
            raise RoadmapError("Choice confirmation expired")
        body = f"{workspace_id}:{roadmap.id}:{roadmap.version}:{expiry}"
        expected = hmac.new(workspace_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(expected, signature):
            raise RoadmapError("Invalid choice confirmation")
        from app.journey import JourneyService
        JourneyService(self.db).set_counselor_stage(
            workspace_id, journey.id, "CHOSEN", actor="human:student", validated_choice=True)
        state.chosen_at = _now()
        draft = journey.counselor_summary_draft or {}
        confirmed_summary = (draft.get("mirror") or draft.get("summary") if draft.get("status") == "confirmed"
                             else None)
        assumptions = []
        if not isinstance(confirmed_summary, dict):
            confirmed_summary = {"stated_goal": {"value": roadmap.title,
                                                  "status": "confirmed_by_route_choice"}}
            assumptions.append("Earlier goal summary was not recorded")
        if roadmap.fit_level == "unconfirmed":
            assumptions.append("Eligibility fit is unconfirmed")
        if any(source.get("status") == "unconfirmed" for source in roadmap.sources or []):
            assumptions.append("Some cited research remains unconfirmed")
        objective = confirmed_summary.get("envisioned_outcome") or {}
        if isinstance(objective, dict):
            objective = objective.get("value")
        decision = DecisionRecord(
            workspace_id=workspace_id, journey_id=journey.id,
            roadmap_id=roadmap.id, roadmap_version=roadmap.version,
            confirmed_summary=confirmed_summary, real_objective=objective or None,
            accepted_gaps=[gap for gap in roadmap.gaps or [] if gap.get("status") != "met"],
            accepted_risks=list(roadmap.risks or []), assumptions=assumptions,
            choice_channel=choice_channel, chosen_at=state.chosen_at)
        self.db.add(decision)
        journey.current_objective = roadmap.title
        journey.active_goal = {"roadmap_id": roadmap.id, "goal_id": roadmap.goal_id,
                               "route": roadmap.route, "title": roadmap.title}
        decisions = list(journey.decisions or [])
        decisions.append({"kind": "roadmap_choice", "roadmap_id": roadmap.id,
                          "chosen_at": state.chosen_at.isoformat(), "version": roadmap.version})
        journey.decisions = decisions
        self.db.flush()
        return self.serialize(roadmap, state)

    def current_decision(self, workspace_id: str) -> dict | None:
        row = self.db.execute(select(DecisionRecord).where(
            DecisionRecord.workspace_id == workspace_id,
        ).order_by(DecisionRecord.chosen_at.desc(), DecisionRecord.id.desc()).limit(1)).scalar_one_or_none()
        if row is None:
            return None
        return {key: getattr(row, key) for key in (
            "id", "journey_id", "roadmap_id", "roadmap_version", "confirmed_summary",
            "real_objective", "accepted_gaps", "accepted_risks", "assumptions",
            "choice_channel") } | {"chosen_at": row.chosen_at.isoformat()}
