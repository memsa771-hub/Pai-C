"""Deterministic counseling state derivation; the LLM executes, not chooses."""

from dataclasses import replace

from app.counseling.state import CounselingMove, CounselingPhase, CounselingState
from .discovery import SUPPRESSED_STATUSES


class CounselingEvaluator:
    def derive(self, *, message: str, vault_context: dict | None,
               journey: dict | None, completion: dict | None,
               recent_conversation: list[dict] | None = None,
               active_conflict: dict | None = None,
               turn_semantics: dict | None = None,
               changed_domains: tuple[str, ...] | list[str] = (),
               recent_question_focus: str | None = None) -> CounselingState:
        state = self._derive(
            message=message, vault_context=vault_context, journey=journey,
            completion=completion, recent_conversation=recent_conversation,
            active_conflict=active_conflict, turn_semantics=turn_semantics,
            changed_domains=changed_domains,
            recent_question_focus=recent_question_focus)
        if state.continuous_discovery is not None:
            return state
        from .continuous_discovery import evaluate_continuous_discovery
        signal = evaluate_continuous_discovery(
            vault_context or {}, turn_semantics, changed_domains=changed_domains,
            active_conflict=active_conflict, journey=journey)
        return replace(state, continuous_discovery=signal.to_dict())

    def _derive(self, *, message: str, vault_context: dict | None,
                journey: dict | None, completion: dict | None,
                recent_conversation: list[dict] | None = None,
                active_conflict: dict | None = None,
                turn_semantics: dict | None = None,
                changed_domains: tuple[str, ...] | list[str] = (),
                recent_question_focus: str | None = None) -> CounselingState:
        missing = (completion or {}).get("missingRequirements", (completion or {}).get("missingCritical", []))
        unknowns = tuple(
            str(item.get("key")) for item in missing
            if isinstance(item, dict) and item.get("key")
        )
        eligible = bool((completion or {}).get("personalizedCounselingEligible", True))
        objective = (journey or {}).get("current_objective")
        blockers = [item for item in ((journey or {}).get("blockers") or [])
                    if item.get("status", "open") == "open"]

        understanding = vault_context or {}
        baseline = understanding.get("baseline") or {}
        semantics = turn_semantics or {}
        if "baseline" in understanding:
            from .decision_sufficiency import DecisionSufficiencyEvaluator, validated_decision_intent
            from .continuous_discovery import evaluate_continuous_discovery
            intent = validated_decision_intent(semantics.get("decision_intent"))
            decision_type = intent["type"] if intent else None
            sufficiency = (DecisionSufficiencyEvaluator().evaluate(
                understanding, decision_type, decision_intent=intent).to_dict()
                if decision_type else None)
            discovery = evaluate_continuous_discovery(
                understanding, semantics, changed_domains=changed_domains,
                decision_sufficiency=sufficiency, active_conflict=active_conflict,
                journey=journey).to_dict()
            relevant_unknowns = tuple(g["focus"] for g in discovery["important_unknowns"])
            conflict = active_conflict or next(iter(understanding.get("open_conflicts") or ()), None)
            requested_work = semantics.get("requested_work") is True
            requested_roadmap = semantics.get("requested_roadmap") is True
            education_focus = self.education_focus(understanding)
            if conflict:
                move = CounselingMove.CLARIFY
                focus = conflict.get("summary") or conflict.get("question") or "conflicting claim"
            elif semantics.get("general_information"):
                move, focus = CounselingMove.REFLECT, "answer the student's question"
            elif semantics.get("mirror_request"):
                move, focus = CounselingMove.REFLECT, "explain that the current profile is in Profile"
            elif semantics.get("wants_progress"):
                move, focus = CounselingMove.COUNSEL, objective or "give a useful next step now"
            elif (requested_work and not blockers
                  and (completion or {}).get("foundationReady") is True
                  and (objective or (understanding.get("goals") or {}).get("nodes"))):
                move = CounselingMove.DELEGATE
                focus = objective or "requested research"
            elif sufficiency and not sufficiency["recommendation_ready"]:
                move = CounselingMove(discovery["next_discovery_move"])
                focus = next((item for item in sufficiency["missing_evidence"]
                              if item != "confirm the current student mirror"), "decision evidence")
            elif requested_roadmap:
                move = CounselingMove.BUILD_ROADMAP
                focus = objective or "requested plan"
            elif discovery["next_discovery_move"] != "NONE":
                move = CounselingMove(discovery["next_discovery_move"])
                focus = discovery["focus"] or "current concern"
            elif education_focus == "current_level" and (understanding.get("documents") or {}).get("nodes"):
                move, focus = CounselingMove.REFLECT, "use uploaded evidence"
            elif education_focus:
                move, focus = CounselingMove.ASK, education_focus
            else:
                move = CounselingMove.COUNSEL
                focus = objective or "current concern"
            if move is CounselingMove.ASK and focus == recent_question_focus:
                move, focus = CounselingMove.REFLECT, "respond to the student's last answer"
            has_context = bool((understanding.get("education") or {}).get("nodes")
                               or (understanding.get("goals") or {}).get("nodes")
                               or (understanding.get("interests") or {}).get("stated"))
            return CounselingState(
                CounselingPhase.COUNSELING if has_context else CounselingPhase.DISCOVERING,
                "low" if has_context else "medium", move, focus,
                move is CounselingMove.DELEGATE and (completion or {}).get("foundationReady") is True,
                move is CounselingMove.BUILD_ROADMAP,
                "full" if has_context and not conflict else "limited", relevant_unknowns,
                conflict, objective,
                1 if move in {CounselingMove.ASK, CounselingMove.CLARIFY,
                              CounselingMove.REQUEST_DOCUMENT} else 0,
                sufficiency, discovery,
            )

        if active_conflict:
            return CounselingState(
                CounselingPhase.REVIEWING, "low", CounselingMove.CLARIFY,
                active_conflict.get("summary") or "conflicting student claim",
                False, False, "none", unknowns, active_conflict, objective, 1,
            )
        if blockers:
            return CounselingState(
                CounselingPhase.REVIEWING, "low", CounselingMove.REVIEW,
                "active blocker", False, False, "limited" if eligible else "none",
                unknowns, None, objective, 1,
            )
        if not eligible:
            return CounselingState(
                CounselingPhase.UNDERSTANDING, "high", CounselingMove.ASK,
                unknowns[0] if unknowns else "student context", False, False,
                "none", unknowns, None, objective, 1,
            )
        if not journey:
            return CounselingState(
                CounselingPhase.ORIENTING, "medium", CounselingMove.ALIGN,
                "goal", False, False, "limited", unknowns, None, None, 1,
            )

        stage = str((journey or {}).get("current_stage") or "").casefold()
        if stage in {"orienting", "orientation"}:
            phase, move = CounselingPhase.ORIENTING, CounselingMove.ALIGN
        elif stage == "understanding":
            phase, move = CounselingPhase.UNDERSTANDING, CounselingMove.ASK
        elif stage in {"aligning", "alignment"}:
            phase, move = CounselingPhase.ALIGNING, CounselingMove.ALIGN
        elif stage in {"planning", "plan"}:
            phase, move = CounselingPhase.PLANNING, CounselingMove.BUILD_ROADMAP
        elif stage in {"review", "reviewing", "decision", "completed"}:
            phase, move = CounselingPhase.REVIEWING, CounselingMove.REVIEW
        elif stage in {"action", "acting", "execution", "application"}:
            phase, move = CounselingPhase.ACTING, CounselingMove.DELEGATE
        elif objective:
            phase, move = CounselingPhase.PLANNING, CounselingMove.BUILD_ROADMAP
        else:
            phase, move = CounselingPhase.ALIGNING, CounselingMove.ALIGN
        decision_ready = phase not in {CounselingPhase.ORIENTING, CounselingPhase.UNDERSTANDING}
        return CounselingState(
            phase, "low", move, objective or "active goal", decision_ready,
            bool(objective) and phase not in {CounselingPhase.ORIENTING, CounselingPhase.UNDERSTANDING},
            "full", unknowns, None, objective, 1,
        )

    @staticmethod
    def relevant_gaps(understanding: dict, focus: str | None = None) -> list[dict]:
        """Choose a relevant thread, not a required-field interview order."""
        gaps = [g for g in understanding.get("open_gaps", [])
                if g.get("status") not in SUPPRESSED_STATUSES]
        return sorted(gaps, key=lambda gap: 0 if gap.get("focus") == focus else 1)

    @staticmethod
    def education_focus(understanding: dict) -> str | None:
        """Build the education backbone gradually without requiring uploads."""
        gaps = {item.get("focus") for item in understanding.get("open_gaps") or ()
                if item.get("status") not in SUPPRESSED_STATUSES}
        return next((focus for focus in ("current_level", "current_qualification",
                                         "current_year", "current_subjects",
                                         "academic_performance") if focus in gaps), None)
