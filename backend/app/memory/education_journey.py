"""Derive broad education history and gaps without inventing records."""

from typing import Any
import re

from .student_snapshot import StudentSnapshot


LEVEL_GROUPS = {
    "pre_university": frozenset({"school", "secondary", "upper_secondary"}),
    "undergraduate": frozenset({"diploma", "associate", "bachelor", "professional"}),
    "postgraduate": frozenset({"master", "mphil", "doctorate"}),
}
GROUP_ORDER = {"pre_university": 0, "undergraduate": 1, "postgraduate": 2, "unknown": 3}
KNOWN_HISTORY_STATUSES = frozenset({"completed", "current"})


def canonical_education_level(level: Any, qualification_name: Any = None) -> str | None:
    """Map common qualification names when extraction omitted the level.

    The result is only a classification hint. It never creates a Vault record
    or overrides an explicit canonical level.
    """
    normalized = str(level or "").strip().casefold()
    if normalized in {item for values in LEVEL_GROUPS.values() for item in values}:
        return normalized
    name = re.sub(r"[^a-z0-9]+", " ", str(qualification_name or "").casefold()).strip()
    words = set(name.split())
    if not words:
        return None
    if "phd" in words or "doctorate" in words:
        return "doctorate"
    if "mphil" in words or ("m" in words and "phil" in words):
        return "mphil"
    if "masters" in words or "master" in words or words & {"ms", "msc", "ma", "mba"}:
        return "master"
    if "bachelor" in words or words & {"bs", "bsc", "ba", "bcom", "bba", "beng"}:
        return "bachelor"
    if "diploma" in words:
        return "diploma"
    if "associate" in words:
        return "associate"
    if words & {"fsc", "fa", "ics", "icom", "hssc"} or ("a" in words and words & {"level", "levels"}):
        return "upper_secondary"
    if "matric" in words or "ssc" in words or ("o" in words and words & {"level", "levels"}):
        return "secondary"
    return None


def education_group(level: Any, qualification_name: Any = None) -> str:
    normalized = canonical_education_level(level, qualification_name)
    for group, levels in LEVEL_GROUPS.items():
        if normalized in levels:
            return group
    return "unknown"


class EducationJourneyService:
    def evaluate(self, snapshot: StudentSnapshot) -> dict:
        records = []
        for source in snapshot.records.get("education", []):
            row = dict(source)
            row["group"] = education_group(row.get("canonical_level"), row.get("qualification_name"))
            records.append(row)

        records.sort(key=self._sort_key)
        gaps: list[dict] = []
        unknown = [row for row in records if row["group"] == "unknown"]
        for row in unknown:
            qualification = row.get("qualification_name") or "this qualification"
            gaps.append({
                "key": f"education_level:{row['id']}",
                "expectedGroup": "unknown",
                "status": "clarification_required",
                "recordId": row["id"],
                "question": f"What level best describes {qualification}?",
            })

        # An unclassified record could itself be the missing prerequisite, so
        # ask what it is before asserting that a broad history group is absent.
        if not unknown:
            completed_history = {
                row["group"] for row in records
                if row.get("academic_status") in KNOWN_HISTORY_STATUSES
            }
            observed_history = {
                row["group"] for row in records
                if row.get("academic_status") != "planned"
            }
            if "postgraduate" in observed_history and "undergraduate" not in completed_history:
                gaps.append({
                    "key": "undergraduate_history",
                    "expectedGroup": "undergraduate",
                    "status": "missing_information",
                    "question": "What qualification did you complete before postgraduate study?",
                })
            if "undergraduate" in observed_history and "pre_university" not in completed_history:
                gaps.append({
                    "key": "pre_university_history",
                    "expectedGroup": "pre_university",
                    "status": "missing_information",
                    "question": "What qualification did you complete before undergraduate study?",
                })

        return {"education": records, "gaps": gaps}

    @staticmethod
    def _sort_key(row: dict) -> tuple:
        known_date = row.get("end_date") or (
            str(row["graduation_year"]) if row.get("graduation_year") else None
        ) or row.get("start_date")
        return (known_date is None, known_date or "", GROUP_ORDER[row["group"]], row.get("id") or "")
