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


def student_group(education_record: dict) -> str | None:
    """The group an education record names, or None when it names none yet.

    None is an answer, not a gap to guess over: FSc without its group, Matric,
    or a degree level leaves the paths waiting for what PAI still needs.
    """
    rules = _data()["group_rules"]
    level = _code("levels", education_record.get("qualification_name"))
    if level in rules["from_field_of_study"]:
        group = _code("intermediate_groups", education_record.get("field_of_study"))
        return group if group in known_groups() else None
    if level in rules["from_level"]:
        return rules["from_level"][level]
    if level in rules["subject_rules"]:
        subjects = _subjects(level, education_record)
        if not subjects:
            return None
        for rule in rules["subject_rules"][level]:
            if set(rule.get("all", [])) <= subjects and (
                    not rule.get("any") or subjects & set(rule["any"])):
                return rule["group"]
    return None
