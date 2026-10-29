# -*- coding: utf-8 -*-
"""The Mirror state card: "you are this", computed from the Vault on every read.

Deterministic and model-free (FOUR_FEATURES_SPEC 2.1), so the card is never
out of date and nothing waits for it. It is a view over three things that
already exist: the coverage areas (which Vault entries cover which area, and
whether the area is known), the Vault view (each entry's English display text
in catalog labels, evidence level, source and date; never the evidence quote),
and the roadmap engine's reading of the education record (level, group,
percent), so the Mirror and the roadmap describe the same student.

Levels, readiness, tension rules, source labels and copy live in
policy/mirror.json. The only model output on the card is the stored text the
background job writes (text_job.py); it is shown as it was last written.
"""

import hashlib
import json
import re
from functools import lru_cache

from app.pai_c.completeness import completeness_from
from app.pai_c.memory import MemoryService, entry_ref, vault_catalog
from app.pai_c.paths.fields import current_education, study_fields
from app.pai_c.policy.controller import at_path, load_data
from app.pai_c.roadmap.engine import education_line, marks_percent, student_standing

_SENTENCE_END = re.compile(r"(?<=[.!])\s+(?=\S)")


@lru_cache(maxsize=1)
def mirror_policy() -> dict:
    return load_data("mirror.json")


def card_version(card: dict) -> str:
    """Digest of everything on the card that comes from the Vault (header,
    areas with their entries, unknowns, ready), never the stored text, so the
    text job can tell whether the card changed since it last wrote. An entry's
    `observed_at` is left out: seeing the same thing again is not a change."""
    content = {key: card[key] for key in ("header", "unknowns", "ready")}
    content["areas"] = [{**area, "entries": [{k: v for k, v in entry.items() if k != "observed_at"}
                                             for entry in area["entries"]]} for area in card["areas"]]
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text or "") if part.strip()]


# ---- study field reading, for the different_field rule -----------------------------

def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip() + " "


@lru_cache(maxsize=1)
def _field_phrases() -> list[tuple[str, str | None, str]]:
    """(phrase, field key, family), longest phrase first: study field titles
    and the words in their brackets ("MBBS (Medicine)"), then field_words."""
    fields = study_fields()
    phrases = []
    for field in fields.values():
        outside = re.sub(r"\(.*?\)", " ", field.title)
        inside = re.findall(r"\((.*?)\)", field.title)
        for phrase in (field.title, outside, *inside):
            if _words(phrase).strip():
                phrases.append((_words(phrase).strip(), field.key, field.family))
    for word, target in mirror_policy()["field_words"].items():
        key = target.get("field")
        family = fields[key].family if key in fields else target.get("family")
        phrases.append((_words(word).strip(), key if key in fields else None, family))
    return sorted(phrases, key=lambda row: -len(row[0]))


def field_of(text) -> tuple[str, str | None] | None:
    """(family, field key or None) a value names, or None when it names none."""
    if not isinstance(text, str) or not text.strip():
        return None
    fields = study_fields()
    code = vault_catalog().choice_code("study_fields", text)
    if code in fields:
        return fields[code].family, code
    words = _words(text)
    for phrase, key, family in _field_phrases():
        if f" {phrase} " in words:
            return family, key
    return None


def _different_field(first, second) -> bool:
    a, b = field_of(first), field_of(second)
    if a is None or b is None:
        return False
    return a[0] != b[0] or (a[1] is not None and b[1] is not None and a[1] != b[1])


RULES = {"different_field": _different_field}


def ready_from(coverage: dict) -> bool:
    """The coverage_requirements.json mode's notebook keys, read as the
    coverage areas mirror.json maps them to; all must be known. Policy state
    and chat context read this from the coverage they already hold."""
    from app.pai_c.deep.coverage import requirements
    ready = mirror_policy()["ready"]
    areas = [area for key in requirements()[ready["mode"]] for area in ready["areas"][key]]
    return all(coverage.get(area, {}).get("covered") and not coverage.get(area, {}).get("stale")
               for area in areas)


# ---- the card -----------------------------------------------------------------------

class MirrorEngine:
    def __init__(self, db):
        self.db = db

    def build(self, workspace_id: str) -> dict:
        policy = mirror_policy()
        areas_policy = load_data("areas_policy.json")
        memory = MemoryService(self.db)
        rows = memory.vault_rows(workspace_id)
        coverage = memory.coverage_areas(workspace_id, rows=rows, with_ids=True)
        completeness = completeness_from(coverage, areas_policy)
        shown = {entry_ref(row.entry): row for row in rows if row.sensitivity != "restricted"}

        education = [row for row in rows if row.entry["kind"] == "record" and row.entry["type"] == "education"]
        records = [row.entry["value"] for row in education]
        current = current_education(records)
        current_ref = next((entry_ref(row.entry) for row in education if row.entry["value"] is current), None)
        line = self._education_line(student_standing(records))

        areas = []
        for key in areas_policy["priority"]:
            row = coverage.get(key, {})
            known = bool(row.get("covered")) and not row.get("stale")
            refs = [ref for ref in row.get("entry_ids", ()) if ref in shown and not shown[ref].entry["stale"]]
            entries = [self._entry(ref, shown[ref], line if ref == current_ref else None) for ref in refs]
            bars = (self._bars(rows, shown[current_ref].entry["id"])
                    if key in policy["education_areas"] and current_ref in refs else [])
            areas.append({"key": key, "label": areas_policy["labels"].get(key, key),
                          "level": self._level(known, entries), "entries": entries, "bars": bars,
                          "tension": []})
        self._tensions(areas, shown)

        card = {"header": {"name": self._name(rows), "education_line": line},
                "areas": areas, "unknowns": completeness["unknowns"], "ready": ready_from(coverage)}
        card["version"] = card_version(card)
        card["text"] = self._text(workspace_id)
        return card

    # ---- pieces ---------------------------------------------------------------------

    @staticmethod
    def _level(known: bool, entries: list[dict]) -> int:
        levels = mirror_policy()["levels"]
        strong = sum(entry["evidence"] in levels["strong"] for entry in entries)
        if not known:
            return 0
        if strong >= levels["strong_entries_for_3"]:
            return 3
        return 2 if strong else 1

    @staticmethod
    def _source_label(row) -> str:
        labels = mirror_policy()["source_labels"]
        document = row.entry.get("document")
        if document and document.get("filename"):
            return document["filename"]
        if row.capture in labels["captures"]:
            return labels["captures"][row.capture]
        return labels["source_types"].get(row.entry.get("source"), labels["default"])

    def _entry(self, ref: str, row, line: dict | None) -> dict:
        entry = row.entry
        if line is not None:
            text = line["text"]
        elif entry["kind"] == "fact":
            text = f"{entry['label']}: {entry['display']}"
        else:
            text = entry["display"] or entry["label"]
        return {"id": ref, "text": text, "evidence": entry["level"], "source_label": self._source_label(row),
                "observed_at": entry["observed_at"]}

    @staticmethod
    def _education_line(standing) -> dict | None:
        """The roadmap engine's education line plus its English text."""
        line = education_line(standing)
        if line is None:
            return None
        copy = mirror_policy()["education_text"]
        groups = copy["groups_joiner"].join(group["label"] for group in line["groups"])
        template = copy["with_percent"] if line["percent"] is not None else copy["without_percent"]
        text = " ".join(template.format(level=line["level_label"], groups=groups,
                                        percent=line["percent"]).split()).replace(" ,", ",")
        return {**line, "text": text}

    @staticmethod
    def _bars(rows, education_id: str) -> list[dict]:
        """Per-subject marks: the courses of the current education record that
        carry a percent or obtained/total marks."""
        bars = []
        for row in rows:
            value = row.entry["value"] if row.entry["type"] == "course" else None
            if not isinstance(value, dict) or value.get("education_id") != education_id:
                continue
            percent = marks_percent({"result": value.get("score") or {}})
            if percent is not None and value.get("name"):
                bars.append({"label": value["name"], "percent": percent})
        return bars

    @staticmethod
    def _tensions(areas: list[dict], shown: dict) -> None:
        """Data-driven pairs (mirror.json tension): mark both areas, resolve nothing."""
        by_key = {area["key"]: area for area in areas}

        def side_values(side):
            area = by_key.get(side["area"])
            for entry in (area or {}).get("entries", ()):
                row = shown[entry["id"]].entry
                if row["type"] != side["kind"] or not isinstance(row["value"], dict):
                    continue
                value = next((found for field in side["fields"]
                              for found in [at_path(row["value"], field)] if found), None)
                if value:
                    yield entry["id"], value

        for rule in mirror_policy()["tension"]:
            check = RULES[rule["rule"]]
            for a_id, a_value in side_values(rule["a"]):
                for b_id, b_value in side_values(rule["b"]):
                    if a_id != b_id and check(a_value, b_value):
                        mark = {"a_id": a_id, "b_id": b_id, "note_key": rule["note_key"]}
                        for key in {rule["a"]["area"], rule["b"]["area"]}:
                            by_key[key]["tension"].append(mark)

    @staticmethod
    def _name(rows) -> str | None:
        facts = {row.entry["type"]: row.entry for row in rows if row.entry["kind"] == "fact"}
        for key in mirror_policy()["header_name_fields"]:
            if key in facts and facts[key]["display"]:
                return facts[key]["display"]
        return None

    def ready(self, workspace_id: str) -> bool:
        """The card's `ready` without building the card: one coverage read."""
        return ready_from(MemoryService(self.db).coverage_areas(workspace_id))

    def _text(self, workspace_id: str) -> dict | None:
        from sqlalchemy import select
        from app.models import StudentJourney
        draft = self.db.scalar(select(StudentJourney.counselor_summary_draft).where(
            StudentJourney.workspace_id == workspace_id, StudentJourney.journey_type == "counselor_decision",
            StudentJourney.status == "active").limit(1)) or {}
        if draft.get("type") != "mirror_state" or not draft.get("text"):
            return None
        return {"sentences": split_sentences(draft["text"]), "version": draft["version"],
                "written_at": draft["written_at"]}
