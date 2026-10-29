"""The roadmap engine: for each live path, can the student get in from their
current education (open / step / not_open / unknown), and what stands between.

Pure and deterministic: no model call and no chat input, so the same Vault and
paths always give the same page, and a Vault or path change shows on the next
read (no jobs, nothing goes stale). Eligibility comes only from education
(spec ROADMAP_ENGINE_SPEC.md §2, option A): budget and city never decide.
Reasons are copy keys with values; the English lives in policy/roadmap.json so
the API and the page render the same words.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache

from app.pai_c.memory import MemoryService, vault_catalog
from app.pai_c.paths.fields import (candidate_fields, current_education, education_readable, group_rules,
                                    known_groups, read_education, student_groups, study_fields)
from app.pai_c.policy.controller import load_data
from app.pai_c.possibilities import PossibilityService
from app.pai_c.roadmap.rules import Rule, grade_list, ibcc_percent, rule_for, rules_as_of

TIMED = {"open", "step"}


def calendar_as_of() -> str | None:
    from app.pai_c.roadmap.calendar import calendar
    return calendar().get("as_of")


@lru_cache(maxsize=1)
def roadmap_policy() -> dict:
    return load_data("roadmap.json")


@dataclass(frozen=True)
class Standing:
    level: str | None
    groups: tuple[str, ...]
    percent: float | int | None
    readable: bool
    field: str | None = None  # a degree student's own study field


@dataclass(frozen=True)
class Need:
    """One thing between the student and the field: kind is marks, bridge,
    check or group; detail carries its values for the route checklist."""
    kind: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    status: str
    reasons: list[dict]
    needs: list[Need]
    tests: list[dict]
    years: int | None
    min_percent: float | None
    student_percent: float | None
    confidence: str | None
    sources: list[str]
    subjects: list[str] = field(default_factory=list)


# ---- the student's standing ----------------------------------------------------

def _intermediate_levels() -> set[str]:
    rules = group_rules()
    return ((set(rules["from_field_of_study"]) | set(rules["from_level"]) | set(rules["subject_rules"]))
            - set(rules["before_intermediate"]))


def _whole(value: float | None) -> float | int | None:
    """One decimal, and 55 rather than 55.0, so "you have {have}%" reads right."""
    if value is None:
        return None
    value = round(float(value), 1)
    return int(value) if value.is_integer() else value


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def marks_percent(record: dict) -> float | int | None:
    """The record's own marks: percentage, else obtained/total (a total below
    the obtained marks is a typo, not a mark), else IBCC grades for subject
    levels (A-level) when they are structured grade codes. None otherwise."""
    result = {**record, **(record.get("result") or {})}
    if _number(result.get("percentage")) and 0 <= result["percentage"] <= 100:
        return _whole(result["percentage"])
    obtained, total = result.get("marks_obtained"), result.get("marks_total")
    if _number(obtained) and _number(total) and 0 <= obtained <= total and total > 0:
        return _whole(obtained / total * 100)
    if read_education(record)[0] in group_rules()["subject_rules"]:
        grades = (record.get("details") or {}).get("grades")
        grades = grades if isinstance(grades, list) else grade_list(result.get("grade"))
        return _whole(ibcc_percent(grades)) if grades else None
    return None


def student_standing(education_records: list[dict]) -> Standing:
    """Where the student stands, from Vault education records (newest first)."""
    current = current_education(education_records)
    if current is None:
        return Standing(level=None, groups=(), percent=None, readable=False)
    level, field_code = read_education(current)
    # Level and marks come from the one record paths read: an intermediate
    # mark never describes a Matric standing, nor a Matric mark an FSc one.
    return Standing(level=level, groups=tuple(sorted(student_groups(current))),
                    percent=marks_percent(current) if level in _intermediate_levels() else None,
                    readable=education_readable(education_records),
                    field=field_code if level in group_rules()["degree_levels"] else None)


# ---- the verdict for one field --------------------------------------------------

def _group(code: str) -> dict:
    return {"code": code, "label": vault_catalog().label("intermediate_groups", code)}


def _route_group(code: str) -> dict:
    """A group as a Matric student would choose it, with the qualification
    that carries it: "FSc Pre-Engineering", or "ICS" where the level is the
    group (group_rules from_level)."""
    rules, catalog = group_rules(), vault_catalog()
    own_level = next((level for level, group in rules["from_level"].items() if group == code), None)
    if own_level:
        route = catalog.label("levels", own_level)
    else:
        route = f"{catalog.label('levels', rules['from_field_of_study'][0])} {_group(code)['label']}"
    return {**_group(code), "route_label": route}


def _facts(rule: Rule | None, field_key: str | None, standing: Standing) -> dict:
    if rule is None:
        return {"tests": [], "years": None, "min_percent": None, "student_percent": standing.percent,
                "confidence": None, "sources": [], "subjects": []}
    return {"tests": [asdict(test) for test in rule.tests_for(field_key)], "years": rule.years_for(field_key),
            "min_percent": rule.min_percent, "student_percent": standing.percent,
            "confidence": rule.confidence, "sources": list(rule.sources),
            "subjects": list(rule.required_subjects)}


def _marks(rule: Rule, percent: float | None) -> tuple[list[dict], list[Need], bool]:
    """(reasons, needs, below the floor) for the rule's percent floor."""
    if rule.min_percent is None:
        return [], [], False
    if percent is None:
        return [{"key": "add_marks", "min": rule.min_percent}], [], False
    if percent < rule.min_percent:
        values = {"min": rule.min_percent, "have": percent}
        return [{"key": "needs_percent", **values}], [Need("marks", values)], True
    return [], [], False


def _for_group(field_key: str, rule: Rule, group: str, percent: float | None) -> tuple[str, list, list]:
    study = study_fields()[field_key]
    marks_reasons, marks_needs, below = _marks(rule, percent)
    open_groups = study.open_to if rule.groups_open is None else rule.groups_open
    if group in open_groups:
        return ("step" if below else "open"), marks_reasons, marks_needs
    if rule.groups_open is None and group in study.check:
        return ("step", [{"key": "check", "note": study.check_note}] + marks_reasons,
                [Need("check", {"note": study.check_note})] + marks_needs)
    for step in rule.groups_with_step:
        if step.group == group and (step.scope_fields is None or field_key in step.scope_fields):
            detail = {"text": step.step, "source": step.source}
            return "step", [{"key": "rule_step", **detail}] + marks_reasons, [Need("bridge", detail)] + marks_needs
    return "not_open", [{"key": "not_open_group", "group_code": group, "group_label": _group(group)["label"]}], []


def _choose_group(field_key: str, level: str) -> tuple:
    """Matric / O-level: the field needs an intermediate group first, read from
    the same candidate data the path analyzer uses (needs_group; none listed
    means every intermediate group opens it)."""
    candidate = candidate_fields({"qualification_name": level}).get(field_key)
    if candidate is None:
        return "not_open", [{"key": "not_open_group", "group_code": level,
                             "group_label": vault_catalog().label("levels", level)}], []
    if not candidate.needs_group:
        return "step", [{"key": "choose_any_group"}], [Need("group", {"groups": []})]
    groups = [_route_group(code) for code in candidate.needs_group]
    return "step", [{"key": "choose_group", "groups": groups}], [Need("group", {"groups": groups})]


def verdict(field_key: str | None, standing: Standing) -> Verdict:
    """Status and route facts for one field from the student's standing; the
    order of checks is the verdict table of the spec."""
    order = roadmap_policy()["status_order"]
    rule = rule_for(field_key) if field_key in study_fields() else None
    rules = group_rules()
    if rule is None:
        status, reasons, needs = "unknown", [{"key": "cannot_check"}], []
    elif standing.level in rules["degree_levels"]:
        status, reasons, needs = "unknown", [{"key": "undergrad_only"}], []
    elif not standing.readable or not (standing.groups or standing.level in rules["before_intermediate"]):
        status, reasons, needs = "unknown", [{"key": "needs_education"}], []
    elif standing.level in rules["before_intermediate"]:
        status, reasons, needs = _choose_group(field_key, standing.level)
    else:
        results = [_for_group(field_key, rule, group, standing.percent) for group in standing.groups]
        status, reasons, needs = min(results, key=lambda result: order.index(result[0]))
    return Verdict(status=status, reasons=reasons, needs=needs, **_facts(rule, field_key, standing))


# ---- the page -------------------------------------------------------------------

def education_line(standing: Standing) -> dict | None:
    """The header line as data: level, group (or a degree's field) and percent
    with their catalog labels; roadmap.json education_line renders it."""
    if standing.level is None:
        return None
    rules = group_rules()
    if standing.field:
        study = study_fields().get(standing.field)
        groups = [{"code": standing.field, "label": study.title if study else standing.field}]
    elif standing.level in rules["from_level"] or standing.level in rules["before_intermediate"]:
        groups = []  # the level names the group (ICS, FA), or no group is chosen yet (Matric, O-level)
    else:
        groups = [_group(code) for code in standing.groups if code in known_groups()]
    return {"level": standing.level, "level_label": vault_catalog().label("levels", standing.level),
            "groups": groups, "percent": standing.percent}


class RoadmapEngine:
    def __init__(self, db):
        self.db = db

    def _education(self, workspace_id: str) -> list[dict]:
        # Read exactly as the path analyzer does, so paths and roadmap agree.
        return [card for card in MemoryService(self.db).profile_cards(workspace_id) if card["kind"] == "education"]

    def build(self, workspace_id: str, today: date | None = None) -> dict:
        """The page. `today` is the request day (routers pass date.today());
        every card's steps and time estimate are read against it."""
        from app.pai_c.roadmap.decisions import RouteDecisionService, done_keys, serialize
        from app.pai_c.roadmap.steps import route_steps
        from app.pai_c.roadmap.timeline import estimate
        today = today or date.today()
        education = self._education(workspace_id)
        records = [card["value"] for card in education]
        standing = student_standing(records)
        # The steps read the very record the standing was read from.
        current = current_education(records)
        current_id = next((card["id"] for card in education if card["value"] is current), None)
        rows = MemoryService(self.db).vault_rows(workspace_id)
        decision = RouteDecisionService(self.db).active(workspace_id)
        order = roadmap_policy()["status_order"]
        cards = []
        for row in PossibilityService(self.db).list(workspace_id):
            if row.status == "dismissed":
                continue
            field_key = (row.study_field or {}).get("key")
            study = study_fields().get(field_key) if field_key else None
            result = verdict(field_key, standing)
            card = {"possibility_id": row.id, "field_key": field_key,
                    "title": study.title if study else row.title,
                    "family": study.family if study else None, "why": row.why,
                    "status": result.status, "verdict": asdict(result)}
            ticks = done_keys(decision) if decision is not None and decision.field_key == field_key else ()
            card["steps"] = route_steps(card, standing, rows, today=today, steps_done=ticks,
                                        record=current, record_id=current_id)
            # Only a field the student can enter has a time to entry.
            card["time"] = (estimate(card["steps"], field_key, today)
                            if result.status in TIMED and card["steps"] else None)
            cards.append(card)
        cards.sort(key=lambda card: order.index(card["status"]))  # stable: path order within a status
        counts = {status: sum(card["status"] == status for card in cards) for status in order}
        return {"education_line": education_line(standing), "standing": asdict(standing),
                "counts": counts, "fields": cards, "rules_as_of": rules_as_of(),
                "calendar_as_of": calendar_as_of(),
                "chosen": serialize(decision, cards) if decision is not None else None}
