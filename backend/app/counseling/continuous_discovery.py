"""Derived, turn-local discovery signal. No language parsing or persistence."""

from dataclasses import asdict, dataclass

from .discovery import SUPPRESSED_STATUSES


@dataclass(frozen=True)
class ContinuousDiscovery:
    new_learning: bool
    affected_domains: tuple[str, ...]
    conflicts: tuple[dict, ...]
    important_unknowns: tuple[dict, ...]
    next_discovery_move: str
    focus: str | None

    def to_dict(self) -> dict:
        return asdict(self)


_EVIDENCE_FOCUS = {
    "education": "current_level",
    "academic_performance": "academic_performance",
    "student_voice": "current_direction",
    "interests": "interests",
    "strength_evidence": "strengths",
    "finance": "budget",
    "destinations": "target_location",
}


def evaluate_continuous_discovery(
    understanding: dict, semantics: dict | None = None, *,
    changed_domains: tuple[str, ...] | list[str] = (),
    decision_sufficiency: dict | None = None,
    active_conflict: dict | None = None,
    journey: dict | None = None,
) -> ContinuousDiscovery:
    """Rank gaps for this turn and suggest one discovery action, if useful."""
    semantics = semantics or {}
    topic = semantics.get("topic_focus")
    changes = tuple(dict.fromkeys(str(domain) for domain in changed_domains if domain))
    conflicts = tuple([active_conflict] if active_conflict else
                      (understanding.get("open_conflicts") or ()))
    evidence = (decision_sufficiency or {}).get("evidence") or {}
    critical = {_EVIDENCE_FOCUS[key] for key, value in evidence.items()
                if value == "insufficient" and key in _EVIDENCE_FOCUS}
    if (decision_sufficiency or {}).get("next_best_move") == "EXPLORE":
        critical.add("interests")
    journey_type = (journey or {}).get("journey_type")
    journey_foci = {
        "study_abroad": {"budget", "target_location", "target_timing"},
        "postgraduate_admission": {"academic_performance", "target_timing"},
        "undergraduate_admission": {"academic_performance", "current_direction"},
        "direction_discovery": {"interests", "motivation", "strengths"},
        "career_exploration": {"interests", "strengths"},
    }.get(journey_type, set())
    ranked = []
    for gap in understanding.get("open_gaps") or ():
        if not isinstance(gap, dict) or gap.get("status") in SUPPRESSED_STATUSES:
            continue
        focus = gap.get("focus")
        if not focus:
            continue
        relevance = ("decision_critical" if focus in critical else
                     "current_conversation" if focus == topic or focus in journey_foci else
                     "useful_later")
        ranked.append({"focus": focus, "domain": gap.get("domain"),
                       "relevance": relevance})
    priority = {"decision_critical": 0, "current_conversation": 1, "useful_later": 2}
    ranked.sort(key=lambda item: (priority[item["relevance"]], item["focus"]))
    important = tuple(item for item in ranked if item["relevance"] != "useful_later")
    if conflicts:
        move, focus = "CLARIFY", conflicts[0].get("summary") or conflicts[0].get("question")
    elif decision_sufficiency and not decision_sufficiency.get("recommendation_ready", False):
        move = decision_sufficiency.get("next_best_move", "ASK")
        move = move if move in {"ASK", "EXPLORE", "CLARIFY"} else "ASK"
        focus = (decision_sufficiency.get("missing_evidence") or [None])[0]
    elif changes:
        move, focus = "REFLECT", changes[0]
    elif topic and any(item["focus"] == topic for item in important):
        has_document = bool((understanding.get("documents") or {}).get("nodes"))
        move = ("REFLECT" if has_document and topic in {
            "current_level", "academic_performance", "education_history"} else "ASK")
        focus = "use uploaded evidence" if move == "REFLECT" else topic
    else:
        move, focus = "NONE", None
    return ContinuousDiscovery(bool(changes), changes, conflicts, important, move, focus)
