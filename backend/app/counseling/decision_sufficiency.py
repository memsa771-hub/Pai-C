"""Decision-specific evidence checks, separate from mirror confirmation."""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass


DECISION_TYPES = frozenset({
    "choose_bachelor_direction", "compare_fields", "choose_subjects",
    "study_abroad_direction", "career_direction", "exploration_next_step",
    "university_shortlist",
})
def _key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "_".join(part for part in "".join(
        char if char.isalnum() else " " for char in text).split())


def validated_decision_intent(raw: object) -> dict | None:
    """Validate a model's semantic intent without interpreting its text."""
    if (not isinstance(raw, dict) or not isinstance(raw.get("type"), str)
            or raw["type"] not in DECISION_TYPES):
        return None
    candidates = raw.get("candidates")
    if not isinstance(candidates, (list, tuple)):
        candidates = []
    names = tuple(dict.fromkeys(name.strip() for name in candidates[:8]
                                if isinstance(name, str) and 0 < len(name.strip()) <= 120))
    result = {"type": raw["type"], "candidates": names}
    scope = raw.get("destination_scope")
    if scope in {"local", "abroad", "open", "unspecified"}:
        result["destination_scope"] = scope
    return result


def _candidate_directions(view: dict, intent: dict | None) -> tuple[dict, ...]:
    found: dict[str, dict] = {}
    requested = {_key(name) for name in (intent or {}).get("candidates", ())}
    def add(name, origin, ownership, status):
        key = _key(name)
        if origin != "message" and requested and key not in requested:
            return
        if key and key not in found:
            label = name.replace("_", " ").title() if isinstance(name, str) and "_" in name else name
            found[key] = {"name": label, "key": key, "origin": origin,
                          "ownership": ownership, "status": status}
    for name in (intent or {}).get("candidates", ()):
        add(name, "message", "student", "considering")
    for item in view.get("voice_statements", {}).get("nodes", []):
        if item.get("voice_type") in {"interest", "direction", "preference", "counterfactual"}:
            add(item.get("direction"), "student_voice", "student", item.get("commitment") or "exploring")
    for item in view.get("goals", {}).get("nodes", []):
        if (item.get("details") or {}).get("direction_status") not in {"rejected", "changed"}:
            add((item.get("details") or {}).get("field_of_study") or item.get("title"),
                "goal", "student", item.get("commitment") or "exploring")
    for item in view.get("explorations", {}).get("nodes", []):
        add(item.get("domain"), "exploration", "student", item.get("activity_status") or "exploring")
    for item in view.get("influences", {}).get("nodes", []):
        add(item.get("suggested_direction"), "external_influence", "external", "suggested")
    return tuple(found.values())[:12]


@dataclass(frozen=True)
class DecisionSufficiency:
    decision_type: str
    baseline_confirmed: bool
    evidence: dict[str, str]
    recommendation_ready: bool
    comparison_ready: bool
    research_ready: bool
    missing_evidence: tuple[str, ...]
    next_best_move: str
    candidates: tuple[str, ...]
    candidate_directions: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


class DecisionSufficiencyEvaluator:
    def evaluate(self, view: dict, decision_type: str, *,
                 decision_intent: dict | None = None, message: str = "") -> DecisionSufficiency:
        if decision_type not in DECISION_TYPES:
            raise ValueError("unsupported decision type")
        baseline = view.get("baseline", {}).get("status") == "confirmed"
        education = view.get("education", {}).get("nodes") or []
        courses = view.get("education", {}).get("courses") or []
        academic = any(node.get("result") for node in education) or any(
            item.get("grade") or item.get("score") for item in courses)
        voice = view.get("student_voice") or {}
        direction = (voice.get("current_direction") or {}).get("status", "unknown")
        interests = view.get("interests", {}).get("stated") or []
        influences = view.get("influences", {}).get("nodes") or []
        directions = _candidate_directions(view, decision_intent)
        candidates = tuple(item["key"] for item in directions)
        exposure = {_key(item.get("domain")): item for item in view.get("exposure", {}).get("domains", [])}
        reflected = {key for key, item in exposure.items() if any(
            row.get("activity_status") == "completed" and row.get("student_reflection")
            for row in item.get("experiences", []))}
        missing_exposure = [item for item in directions if item["key"] not in reflected]
        strengths = bool(view.get("projects", {}).get("nodes") or
                         view.get("activities", {}).get("nodes") or
                         view.get("experience", {}).get("nodes") or
                         any(row.get("supported_by") for row in view.get("skills", {}).get("nodes", [])))
        own_preference = bool(interests or direction in {"exploring", "committed"})
        voice_status = ("known" if direction == "committed" else
                        "partial" if own_preference or direction == "uncertain" else "insufficient")
        evidence = {
            "education": "known" if education else "insufficient",
            "academic_performance": "known" if academic else "insufficient",
            "student_voice": voice_status,
            "interests": "known" if interests else "insufficient",
            "exposure": ("known" if len(reflected) >= 2 and not missing_exposure else
                         "partial" if reflected else "insufficient"),
            "strength_evidence": "known" if strengths else "insufficient",
            "external_influences": "known" if influences else "not_recorded",
        }
        missing = []
        comparison = bool(education) and academic and len(candidates) >= 2
        research = bool(candidates or direction in {"exploring", "committed"})
        if decision_type in {"choose_bachelor_direction", "compare_fields"}:
            if not education:
                missing.append("current education")
            if not academic:
                missing.append("academic performance in relevant subjects")
            if not own_preference or direction == "uncertain":
                missing.append("the student's own preference apart from outside suggestions")
            if len(candidates) < 2:
                missing.append("at least two directions to compare")
            missing.extend(f"practical exposure to {item['name']}" for item in missing_exposure)
            ready = bool(education) and academic and own_preference and direction != "uncertain" and len(candidates) >= 2 and not missing_exposure
        elif decision_type == "choose_subjects":
            if not education:
                missing.append("current education")
            if not academic:
                missing.append("academic performance in relevant subjects")
            if not own_preference:
                missing.append("student's own subject interests")
            ready = bool(education) and academic and own_preference
            comparison = bool(education) and academic
        elif decision_type == "study_abroad_direction":
            finance = view.get("finance") or {}
            budget = bool(finance.get("facts", {}).get("budget") or finance.get("sponsors"))
            destinations = bool(view.get("preferences", {}).get("target_countries") or any(
                (goal.get("details") or {}).get("target_countries")
                for goal in view.get("goals", {}).get("nodes", [])))
            if not education:
                missing.append("current education")
            if not own_preference:
                missing.append("student's own study direction")
            if not budget:
                missing.append("funding context")
            if not destinations:
                missing.append("destinations under consideration")
            evidence.update(finance="known" if budget else "insufficient",
                            destinations="known" if destinations else "insufficient")
            ready = bool(education) and own_preference and budget and destinations
            comparison = bool(education) and destinations
        elif decision_type == "career_direction":
            if not own_preference:
                missing.append("student's own career interests")
            if not strengths:
                missing.append("examples of strengths in practice")
            missing.extend(f"practical exposure to {item['name']}" for item in missing_exposure)
            ready = own_preference and strengths and bool(candidates) and not missing_exposure
            comparison = len(candidates) >= 2 and strengths
        elif decision_type == "university_shortlist":
            preferences = view.get("preferences") or {}
            goals = view.get("goals", {}).get("nodes") or []
            finance = view.get("finance") or {}
            funding = bool(finance.get("facts", {}).get("budget") or finance.get("sponsors"))
            timing = bool(preferences.get("target_timing") or any(
                goal.get("target_date") or (goal.get("details") or {}).get("target_intake")
                for goal in goals))
            destination = bool((decision_intent or {}).get("destination_scope") in
                               {"local", "abroad", "open"} or preferences.get("target_countries") or any(
                (goal.get("details") or {}).get("target_countries") for goal in goals))
            field = bool((decision_intent or {}).get("candidates") or interests or any(
                (goal.get("details") or {}).get("field_of_study") for goal in goals))
            if not education:
                missing.append("current qualification")
            if not field:
                missing.append("intended field of study")
            if not academic:
                missing.append("approximate or predicted grades")
            if not destination:
                missing.append("study destination or region")
            if not funding:
                missing.append("funding range or scholarship need")
            if not timing:
                missing.append("target intake timing")
            evidence.update(field_of_study="known" if field else "insufficient",
                            destinations="known" if destination else "insufficient",
                            finance="known" if funding else "insufficient")
            ready = bool(education) and field and destination and academic and funding and timing
            comparison = ready
        else:  # exploration_next_step is a low-stakes process choice.
            if not (interests or direction == "uncertain" or candidates):
                missing.append("a direction or uncertainty to explore")
            ready = not missing
            comparison = False
        if ready:
            next_move = "COUNSEL"
        elif missing_exposure and decision_type in {"choose_bachelor_direction", "compare_fields", "career_direction"}:
            next_move = "EXPLORE"
        elif influences and not own_preference:
            next_move = "CLARIFY"
        else:
            next_move = "ASK"
        return DecisionSufficiency(decision_type, baseline, evidence, ready, comparison,
                                   research, tuple(dict.fromkeys(missing)), next_move,
                                   candidates, directions)


def guard_premature_verdict(response: str, result: dict | None, *,
                           final_recommendation: bool | None = None) -> str:
    """Use the Counselor's structured declaration, not an English phrase scan."""
    if not result or result.get("recommendation_ready") or result.get("decision_type") == "exploration_next_step":
        return response
    if final_recommendation is False:
        return response
    missing = result.get("missing_evidence") or []
    if result.get("decision_type") == "university_shortlist":
        questions = {
            "current qualification": "What qualification are you studying now?",
            "intended field of study": "What subject do you want to study?",
            "approximate or predicted grades": "What are your approximate or predicted grades?",
            "study destination or region": "Are you looking locally or abroad?",
            "funding range or scholarship need": "What funding range or scholarship need should I plan around?",
            "target intake timing": "When would you like to start?",
        }
        question = next((questions[item] for item in missing if item in questions), None)
        return ("I can help narrow university options using what you've shared. "
                + (question + " An estimate is fine." if question else
                   "Let's check the remaining match factors before narrowing the list."))
    exposure = next((item for item in missing if item.startswith("practical exposure to ")), None)
    next_step = (f"A useful next step is to try a small activity in {exposure.removeprefix('practical exposure to ')} "
                 "and reflect on how you felt doing the work." if exposure else
                 "Let's clarify one of those missing pieces before choosing.")
    return ("I can compare the evidence we have, but I cannot recommend a final choice yet. "
            + next_step)
