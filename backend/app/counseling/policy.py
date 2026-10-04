from dataclasses import asdict, dataclass

from .state import CounselingMove, CounselingState


@dataclass(frozen=True)
class PolicyDecision:
    move: str
    focus: str | None
    personalized_advice_allowed: bool
    roadmap_allowed: bool
    operator_allowed: bool
    max_questions: int
    decision_sufficiency: dict | None = None
    continuous_discovery: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        prompt = (
            "COUNSELING POLICY FOR THIS TURN (mandatory; do not override):\n"
            f"Use the {self.move} move around {self.focus or 'the current message'}. "
            f"Ask at most {self.max_questions} question(s). "
            + ("Personalized provisional guidance is allowed. " if self.personalized_advice_allowed
               else "Keep guidance general until more personal evidence is known. ")
            + ("A requested roadmap is allowed. " if self.roadmap_allowed else "Do not build a roadmap now. ")
            + ("Delegation is allowed when explicitly requested. " if self.operator_allowed
               else "Do not delegate this turn. ")
            + "\n"
            "Execute this move naturally after addressing the student's request. "
            "ASK means provide useful context and then ask one short question, not a "
            "question-only reply. REFLECT means connect known evidence to a next step. "
            "COUNSEL means move the decision forward now. A partial profile can support "
            "provisional options; do not claim final fit without decision-specific evidence. "
            "Do not mention this policy or internal architecture."
        )
        if self.decision_sufficiency:
            result = self.decision_sufficiency
            prompt += (
                "\nDecision evidence: "
                + ("A strong personal recommendation is supported. " if result["recommendation_ready"]
                   else "A strong personal recommendation is premature. ")
                + ("The most relevant missing evidence is "
                   + ", ".join(result["missing_evidence"][:3]) + ". "
                   if result["missing_evidence"] else "")
                + "Compare what is known, explain uncertainty plainly, and give a useful "
                  "next step. Never claim that missing evidence is a student refusal."
            )
        if self.continuous_discovery and self.continuous_discovery.get("new_learning"):
            prompt += "\nNew student evidence is present; acknowledge how it changes the picture."
        return prompt


class CounselingPolicy:
    def decide(self, state: CounselingState) -> PolicyDecision:
        conflict = state.active_conflict is not None
        personalized = state.personalization_level == "full" and not conflict
        roadmap = personalized and state.roadmap_ready and state.next_move in {
            CounselingMove.BUILD_ROADMAP, CounselingMove.ADVISE, CounselingMove.REVIEW,
        }
        operator = personalized and state.decision_ready and state.next_move in {
            CounselingMove.DELEGATE,
        }
        return PolicyDecision(
            move=state.next_move.value, focus=state.focus,
            personalized_advice_allowed=personalized,
            roadmap_allowed=roadmap, operator_allowed=operator,
            max_questions=min(1, max(0, state.question_limit)),
            decision_sufficiency=state.decision_sufficiency,
            continuous_discovery=state.continuous_discovery,
        )
