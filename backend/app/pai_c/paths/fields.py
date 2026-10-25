"""Study fields and the student's group: which fields a path may name.

Paths are real fields of study (Electrical Engineering, MBBS, BBA), and a
student's intermediate group decides which of them are open. Both the fields
and the rule for reading a group off an education record live in
policy/study_fields.json, so correcting an admission rule is a data change.
`check` fields are never treated as open: the conditions vary by university and
must be researched before PAI tells a student they qualify.
"""

from dataclasses import dataclass
from functools import lru_cache

from app.pai_c.policy.controller import load_data


@dataclass(frozen=True)
class StudyField:
    key: str
    title: str
    family: str
    levels: list[str]
    isced: str
    open_to: list[str]
    check: list[str]
    check_note: str = ""


@lru_cache(maxsize=1)
def _data() -> dict:
    return load_data("study_fields.json")


def known_groups() -> set[str]:
    return set(_data()["groups"])


@lru_cache(maxsize=1)
def study_fields() -> dict[str, StudyField]:
    return {row["key"]: StudyField(
        key=row["key"], title=row["title"], family=row["family"], levels=list(row["levels"]),
        isced=row["isced"], open_to=list(row["open_to"]), check=list(row.get("check", [])),
        check_note=row.get("check_note", "")) for row in _data()["fields"]}


def fields_for_group(group_code: str) -> tuple[list[StudyField], list[StudyField]]:
    """(open, check) for a group, in file order; an unknown group opens nothing."""
    fields = study_fields().values()
    return ([f for f in fields if group_code in f.open_to],
            [f for f in fields if group_code in f.check])


def _code(list_name: str, value) -> str | None:
    """A stored value may be a code or the student's wording ("FSc", "Pre-Medical")."""
    from app.pai_c.memory import vault_catalog  # PAI C reads app.memory through its one owner
    return vault_catalog().choice_code(list_name, value) if isinstance(value, str) and value else None


def _subjects(level: str, record: dict) -> set[str]:
    raw = record.get("subjects") or (record.get("details") or {}).get("subjects") or []
    return {code for code in (_code(f"{level}_subjects", s) for s in raw) if code}


def _subject_groups(rules: list[dict], subjects: set[str]) -> list[str]:
    """Groups whose subject rule matches, in file order; a catch-all rule (no
    subjects listed) is last and counts only when nothing else matched."""
    if not subjects:
        return []
    matched = [rule["group"] for rule in rules if (rule.get("all") or rule.get("any"))
               and set(rule.get("all", [])) <= subjects and (not rule.get("any") or subjects & set(rule["any"]))]
    return matched or [rule["group"] for rule in rules if not rule.get("all") and not rule.get("any")][:1]


def student_groups(education_record: dict) -> set[str]:
    """Every group an education record names. A-level subjects can satisfy
    more than one group (Biology, Chemistry, Physics and Maths open both
    Pre-Medical and Pre-Engineering fields), so paths use the union."""
    rules = _data()["group_rules"]
    level = _code("levels", education_record.get("qualification_name"))
    if level in rules["from_field_of_study"]:
        group = _code("intermediate_groups", education_record.get("field_of_study"))
        return {group} if group in known_groups() else set()
    if level in rules["from_level"]:
        return {rules["from_level"][level]}
    if level in rules["subject_rules"]:
        return set(_subject_groups(rules["subject_rules"][level], _subjects(level, education_record)))
    return set()


def student_group(education_record: dict) -> str | None:
    """The first group an education record names, or None when it names none yet.

    None is an answer, not a gap to guess over: FSc without its group, Matric,
    or a degree level leaves the paths waiting for what PAI still needs.
    """
    rules = _data()["group_rules"]
    level = _code("levels", education_record.get("qualification_name"))
    if level in rules["subject_rules"]:
        groups = _subject_groups(rules["subject_rules"][level], _subjects(level, education_record))
        return groups[0] if groups else None
    groups = student_groups(education_record)
    return next(iter(groups)) if groups else None


@dataclass(frozen=True)
class Candidate:
    """A field a path may name for this student, and how it stands:
    open, check (conditions vary, research decides) or needs_group (a Matric
    or O-level student who must still choose an intermediate group)."""
    field: StudyField
    standing: str
    needs_group: tuple[str, ...] = ()


def candidate_fields(education_record: dict | None) -> dict[str, Candidate]:
    """The only fields the path analyzer may choose from, by the student's
    current education. Empty when the education is missing or unknown: PAI
    then suggests nothing and says what it still needs."""
    if not education_record:
        return {}
    fields = study_fields()
    level = _code("levels", education_record.get("qualification_name"))
    rules = _data()["group_rules"]
    if level in rules["before_intermediate"]:
        intermediate = known_groups() - set(rules["not_intermediate"])
        result = {}
        for key, field in fields.items():
            needs = tuple(g for g in field.open_to if g in intermediate)
            if not needs:
                continue
            result[key] = (Candidate(field, "open") if set(needs) == intermediate
                           else Candidate(field, "needs_group", needs))
        return result
    if level in rules["degree_levels"]:
        current = fields.get(_code("study_fields", education_record.get("field_of_study")) or "")
        if current is None:
            return {}
        # A degree student's next step is the level above: only fields offered there.
        following = set(rules["degree_levels"][level])
        return {key: Candidate(field, "open" if field.family == current.family else "check")
                for key, field in fields.items() if following & set(field.levels)}
    groups = student_groups(education_record)
    result: dict[str, Candidate] = {}
    for group in sorted(groups):
        open_, check = fields_for_group(group)
        for field in open_:
            result[field.key] = Candidate(field, "open")
        for field in check:
            result.setdefault(field.key, Candidate(field, "check"))
    return {key: result[key] for key in fields if key in result}


def current_education(records: list[dict]) -> dict | None:
    """The education record paths read: a current one first, then the highest
    level (the order lives in study_fields.json), then the first stored."""
    order = _data()["group_rules"]["level_order"]

    def rank(row: dict) -> tuple[bool, int]:
        level = _code("levels", row.get("qualification_name"))
        return row.get("academic_status") == "current", order.index(level) if level in order else -1

    return max(records, key=rank, default=None)
