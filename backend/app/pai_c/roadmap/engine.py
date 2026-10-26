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
from functools import lru_cache

from app.pai_c.memory import MemoryService, vault_catalog
from app.pai_c.paths.fields import (candidate_fields, current_education, education_readable, group_rules,
                                    known_groups, read_education, student_groups, study_fields)
from app.pai_c.policy.controller import load_data
from app.pai_c.possibilities import PossibilityService
from app.pai_c.roadmap.rules import Rule, grade_list, ibcc_percent, rule_for


@lru_cache(maxsize=1)
def roadmap_policy() -> dict:
    return load_data("roadmap.json")


@dataclass(frozen=True)
class Standing:
    level: str | None
    groups: tuple[str, ...]
    percent: float | None
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


def _marks_record(records: list[dict], current: dict | None) -> dict | None:
    """The intermediate-level record, completed or current: the current
    education when it is one, else the most recent such record."""
    levels = _intermediate_levels()
    usable = [row for row in records if read_education(row)[0] in levels
              and row.get("academic_status") in (None, "current", "completed")]
    return current if current in usable else (usable[0] if usable else None)


def _percent(record: dict | None) -> float | None:
    if not record:
        return None
    result = {**record, **(record.get("result") or {})}
    if isinstance(result.get("percentage"), (int, float)):
        return round(float(result["percentage"]), 1)
    obtained, total = result.get("marks_obtained"), result.get("marks_total")
    if isinstance(obtained, (int, float)) and isinstance(total, (int, float)) and total > 0:
        return round(obtained / total * 100, 1)
    if read_education(record)[0] in group_rules()["subject_rules"]:
        grades = (record.get("details") or {}).get("grades") or grade_list(result.get("grade"))
        value = ibcc_percent(list(grades)) if grades else None
        return round(value, 1) if value is not None else None
    return None


def student_standing(education_records: list[dict]) -> Standing:
    """Where the student stands, from Vault education records (newest first)."""
    current = current_education(education_records)
    if current is None:
        return Standing(level=None, groups=(), percent=None, readable=False)
    level, field_code = read_education(current)
    return Standing(level=level, groups=tuple(sorted(student_groups(current))),
                    percent=_percent(_marks_record(education_records, current)),
                    readable=education_readable(education_records),
                    field=field_code if level in group_rules()["degree_levels"] else None)


# ---- the verdict for one field --------------------------------------------------

def _group(code: str) -> dict:
    return {"code": code, "label": vault_catalog().label("intermediate_groups", code)}


def _facts(rule: Rule | None, field_key: str | None, standing: Standing) -> dict:
    if rule is None:
        return {"tests": [], "years": None, "min_percent": None, "student_percent": standing.percent,
                "confidence": None, "sources": [], "subjects": []}
    return {"tests": [asdict(test) for test in rule.entry_tests], "years": rule.years_for(field_key),
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
    groups = [_group(code) for code in candidate.needs_group]
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
    elif standing.level in rules["from_level"]:
        groups = []  # the level already names the group (ICS, I.Com, FA, DAE)
    else:
        groups = [_group(code) for code in standing.groups if code in known_groups()]
    return {"level": standing.level, "level_label": vault_catalog().label("levels", standing.level),
            "groups": groups, "percent": standing.percent}


class RoadmapEngine:
    def __init__(self, db):
        self.db = db

    def _education(self, workspace_id: str) -> list[dict]:
        # Read exactly as the path analyzer does, so paths and roadmap agree.
        return [card["value"] for card in MemoryService(self.db).profile_cards(workspace_id)
                if card["kind"] == "education"]

    def build(self, workspace_id: str) -> dict:
        records = self._education(workspace_id)
        standing = student_standing(records)
        order = roadmap_policy()["status_order"]
        cards = []
        for row in PossibilityService(self.db).list(workspace_id):
            if row.status == "dismissed":
                continue
            field_key = (row.study_field or {}).get("key")
            study = study_fields().get(field_key) if field_key else None
            result = verdict(field_key, standing)
            cards.append({"possibility_id": row.id, "field_key": field_key,
                          "title": study.title if study else row.title,
                          "family": study.family if study else None, "why": row.why,
                          "status": result.status, "verdict": asdict(result)})
        cards.sort(key=lambda card: order.index(card["status"]))  # stable: path order within a status
        counts = {status: sum(card["status"] == status for card in cards) for status in order}
        return {"education_line": education_line(standing), "standing": asdict(standing),
                "counts": counts, "fields": cards, "chosen": self._chosen(workspace_id)}

    def _chosen(self, workspace_id: str):
        """The active route decision; Task 3 (pai_route_decisions) fills this seam."""
        return None
