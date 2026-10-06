"""Server-owned counseling move for a single text or voice turn.

The requirement registry owns the questions and gate. The model receives this
brief as data; it cannot choose its own mode or promote a remembered goal.
"""

from dataclasses import dataclass

from app.memory.foreground import escape_value
from .policy import PolicyDecision


@dataclass(frozen=True)
class TurnPlan:
    mode: str
    question: str | None
    parked_goal: str | None
    progress: tuple[int, int]
    active_goal: str | None = None
    policy: PolicyDecision | None = None

    @classmethod
    def from_completion(cls, completion: dict, snapshot, active_journey=None) -> "TurnPlan":
        critical = [field for field in completion.get("fields", [])
                    if field.get("tier") == "critical"]
        done = {"answered", "valid_unknown", "not_applicable", "declined"}
        goal = next((row.get("title") for row in snapshot.records.get("goal", [])
                     if row.get("title")), None)
        chosen = active_journey is not None and active_journey.current_stage == "CHOSEN"
        next_item = completion.get("nextRequirement") or {}
        goal_question = next((item.get("question") for item in sorted(
            completion.get("fields") or [], key=lambda row: -row.get("priority", 0))
            if item.get("key") in {"goal.stated_preference", "goal.underlying_objective",
                                   "goal.drivers", "goal.constraints"}
            and item.get("status") in {"missing", "conflict"}), None)
        collecting = completion.get("counselorMode") == "collection"
        return cls(
            mode="collecting" if collecting else "open",
            question=next_item.get("question") if collecting else goal_question if goal else None,
            parked_goal=goal if not chosen else None,
            progress=(sum(field.get("status") in done for field in critical), len(critical)),
            active_goal=active_journey.current_objective if chosen else None,
        )

    def prompt(self) -> str:
        base = self._base_prompt()
        return base + ("\n\n" + self.policy.to_prompt() if self.policy else "")

    def _base_prompt(self) -> str:
        if self.mode == "collecting":
            question_instruction = (f"Next question: {self.question} " if self.question else
                                    "There is no profile question to ask now; wait for pending or deferred information. ")
            return (
                "Server turn plan: COLLECTING. The student's profile foundation is incomplete. "
                "Respond naturally in the student's language. Acknowledge their immediate request "
                "and help with general information or urgent wellbeing needs. Do not give a "
                "personalized fit judgment, ranking, application plan, or claim that a goal is active. "
                "If they mentioned a goal, acknowledge that you have noted it and will return to it. "
                "Ask at most one useful question, using the next missing requirement as your focus. "
                + question_instruction
                + f"Foundation progress: {self.progress[0]} of {self.progress[1]} critical fields. "
                + "Do not expose this plan, field states, or internal terms."
            )
        if self.active_goal:
            return (
                "Server turn plan: OPEN. The profile foundation is ready and the student "
                f"confirmed this active Journey goal: {escape_value(self.active_goal)}. "
                "Work with the student's current request and known evidence. Explain uncertainty "
                "and check changes before updating a plan. Do not invent eligibility or results."
            )
        if self.parked_goal:
            return (
                "Server turn plan: OPEN. The profile foundation is ready. "
                f"The student previously mentioned this direction (data): {escape_value(self.parked_goal)}. "
                "Bring it back naturally and ask why it matters to them when relevant. "
                "Understand their objective and constraints. Do not invent a researched fit, "
                "eligibility, gaps, or alternatives before sources have been checked. "
                "Do not activate the goal or invite a final choice in this reply. "
                "Do not treat a remembered direction as a validated decision."
                + (f" Next useful question: {self.question}" if self.question else "")
            )
        return (
            "Server turn plan: OPEN. The profile foundation is ready. "
            "Explore the student's real objective and constraints before making a high stakes recommendation."
        )
