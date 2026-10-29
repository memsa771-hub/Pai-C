# -*- coding: utf-8 -*-
"""The Vault view: one read model of everything the Vault holds about a student.

A VIEW, never a second source of truth: facts, records and catalog items are
read from their own stores and shaped into the Details sections, the story
cards, the open conflict cards and the entries due for re-confirmation. Nothing
here writes.

Rules this module exists to enforce (VAULT_SPEC §Language, §Evidence ladder,
§Conflicts, §Freshness, §Access):

1. **Never the student's original words.** Entries are built from an explicit
   list of keys; `evidence` (the verbatim quote, corroborations, model output)
   never passes through. Values are the stored English values, and choice
   codes are also rendered as their catalog labels in `display`.
2. **One evidence ladder.** Facts and records take their level from
   `evidence.evidence_level` plus the guess rung; items carry their own level.
   The badge copy comes from vault_view.json, and an open question overrides it.
3. **Documents open the right file.** The link is the evidence's file id and
   page, with the filename from the workspace file table. A deleted file drops
   the link, never the value.
4. **The catalog decides placement.** A type's section, label, sensitivity and
   freshness window come from its catalog entry, so a new type needs no code.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import select

from app.models import FileRecord, MemoryCandidate, ProfileIssue, VaultFact, VaultItem

from .catalog import TypeSpec, vault_catalog
from .evidence import evidence_level, page_of
from .student_records import ENTITY_MODELS, StudentRecordService
from .vault import _unwrap, is_guess
from .vault_items import VaultItemService

HIDDEN_WHEN_NOT_SENSITIVE = ("sensitive", "restricted")
# A record kind vault_view.json marks hidden is never shown, to anyone.
NEVER_SHOWN = "hidden"


@lru_cache(maxsize=1)
def view_copy() -> dict:
    """Badge copy, section labels and conflict card wording live in data."""
    return json.loads(Path(__file__).with_name("vault_view.json").read_text(encoding="utf-8"))


def level_of(source_type: Optional[str], verification_status: Optional[str], evidence: Optional[dict], *,
             value: Any = None, capture_method: Optional[str] = None) -> str:
    """The evidence ladder for a fact or record: inferred < stated < shown < confirmed.

    Built on `evidence_level` (confirmation, unconfirmed OCR or unverified
    owner, document authority) and adds the guess rung it does not know: a
    value PAI inferred, or one an agent or the system produced, is PAI's guess
    unless a document or the student's confirmation stands behind it.
    `value` and `capture_method` are needed only to recognise a confirmation.
    """
    row = {"source_type": source_type, "verification_status": verification_status,
           "capture_method": capture_method, "evidence": evidence or {}}
    level = evidence_level(row, value)
    return "inferred" if level == "stated" and is_guess(source_type, evidence) else level


def badge_for(level: str, in_question: bool) -> str:
    badges = view_copy()["badges"]
    return badges["in_question"] if in_question else badges[level]


def _aware(moment: Any) -> Optional[datetime]:
    """SQLite hands back naive UTC and evidence holds ISO text; compare as aware UTC."""
    if moment is None:
        return None
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment)
        except ValueError:
            return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.isoformat() if moment else None


def _skip_in_display(key: str) -> bool:
    return key == "id" or key.endswith("_id") or key.endswith("_ids") or key == "evidence_refs"


def _enum_codes(type_key: Optional[str]) -> dict[str, set]:
    """field path -> the enum codes its schema allows, from wherever the type's
    shape lives (an item schema, a fact's validation schema, a record spec), so
    a schema code with no catalog list ("considering", "high") still reads as
    words."""
    from .student_schema import RECORD_SPECS

    spec = vault_catalog().type(type_key) if type_key else None
    schema = None
    if spec is not None and spec.schema:
        schema = spec.schema
    elif spec is not None and spec.field_definition:
        schema = spec.field_definition.get("validation_schema")
    elif type_key in RECORD_SPECS:
        schema = {"properties": RECORD_SPECS[type_key]["properties"]}
    codes: dict[str, set] = {}

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        if node.get("enum"):
            codes[path] = {str(c) for c in node["enum"]}
        if isinstance(node.get("items"), dict):
            walk(node["items"], path)
        for key, child in (node.get("properties") or {}).items():
            walk(child, f"{path}.{key}" if path else key)

    walk(schema, "")
    return codes


def _number(value: Any) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _result_text(result: dict) -> str:
    """A result as the student reads it on a result card: "470/550 (85%)"."""
    words = view_copy()["display"]["result"]
    got, total, pct = result.get("marks_obtained"), result.get("marks_total"), result.get("percentage")
    if isinstance(got, (int, float)) and isinstance(total, (int, float)) and total > 0:
        pct = pct if isinstance(pct, (int, float)) else round(got * 100 / total)
        return words["marks"].format(obtained=_number(got), total=_number(total), percent=_number(pct))
    if isinstance(pct, (int, float)):
        return words["percent"].format(percent=_number(pct))
    if isinstance(result.get("gpa"), (int, float)):
        scale = result.get("gpa_scale")
        return (words["gpa_scale"] if scale else words["gpa"]).format(
            gpa=_number(result["gpa"]), scale=_number(scale) if scale else "")
    if result.get("grade"):
        return words["grade"].format(grade=result["grade"])
    return ""


def _budget_amount(value: dict) -> str:
    """The budget as its band label; a range or amount the student gave reads
    as the band it falls in, else in lakh ("3-8 lakh"), never as 600000."""
    catalog, rules = vault_catalog(), view_copy()["display"]["budget"]
    if value.get("band"):
        return catalog.label("budget_bands", value["band"])
    figures = [value.get(k) for k in rules["amount_fields"]]
    figures = [f for f in figures if isinstance(f, (int, float)) and not isinstance(f, bool)]
    if not figures:
        return ""
    low, high = min(figures), max(figures)
    for code, (start, end) in rules["band_ranges"].items():
        if start <= low and (end is None or high <= end):
            return catalog.label("budget_bands", code)

    def lakh(n):
        return _number(round(n / rules["lakh"], 1))

    text = lakh(low) if low == high else f"{lakh(low)}-{lakh(high)}"
    return rules["lakh_template"].format(amount=text)


def _display(spec: Optional[TypeSpec], value: Any, type_key: Optional[str] = None) -> str:
    """English text for a value, one line: choice codes become catalog labels,
    schema codes become words, marks read as "470/550 (85%)", a budget as its
    band, and ids and internal fields are left out (no raw codes on any page).
    What a type shows, in what order, lives in vault_view.json."""
    catalog = vault_catalog()
    rules = view_copy()["display"]
    type_key = spec.key if spec is not None else type_key
    shape = rules["types"].get(type_key or "", {})
    # A field read against the record's own level: a matric group, a DAE
    # technology or a study field, never a raw code on the Details page.
    choices = dict(catalog.record_choice_fields(spec, value))
    if spec is not None and spec.key == "education" and isinstance(value, dict):
        level = catalog.record_level(spec, value)
        if level and f"{level}_subjects" in catalog.choice_names():
            choices["details.subjects"] = f"{level}_subjects"
    wordings = shape.get("wordings", {})
    choices.update(wordings)
    enums = _enum_codes(type_key)
    hidden = set(rules["hidden_fields"]) | set(shape.get("hidden", ()))

    def word(node: str, path: str) -> str:
        name = path.rsplit(".", 1)[-1]
        if path in choices:
            code = catalog.choice_code(choices[path], node)
            if code is not None:
                return catalog.label(choices[path], code)
            if path in wordings:  # free text where a list was hoped for
                return node[:1].upper() + node[1:]
        if node in rules["enum_labels"].get(name, {}):
            return rules["enum_labels"][name][node]
        if node in enums.get(path, ()):
            text = node.replace("_", " ")
            return text[:1].upper() + text[1:]
        return node

    def render(node: Any, path: str) -> list:
        name = path.rsplit(".", 1)[-1]
        if node is None or node == "" or (path and (_skip_in_display(name) or name in hidden)):
            return []
        if name == "result" and isinstance(node, dict):
            parts = [_result_text(node)]
        elif isinstance(node, bool):
            parts = [rules["yes"] if node else rules["no"]]
        elif isinstance(node, dict):
            parts = [p for k, v in node.items() for p in render(v, f"{path}.{k}" if path else k)]
        elif isinstance(node, list):
            parts = [p for v in node for p in render(v, path)]
        elif isinstance(node, str):
            parts = [word(node, path)]
        elif isinstance(node, (int, float)):
            parts = [_number(node)]
        else:
            parts = [str(node)]
        template = rules["field_templates"].get(name)
        return [template.format(value=p) if template else p for p in parts if p]

    if type_key == "finance.budget" and isinstance(value, dict):
        parts = [_budget_amount(value)] + render(
            {k: v for k, v in value.items() if k not in rules["budget"]["amount_fields"]}, "")
    elif shape.get("fields") and isinstance(value, dict):
        parts = []
        for path in shape["fields"]:
            node = value
            for part in path.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            parts += render(node, path)
    elif shape.get("order") and isinstance(value, dict):
        # A record's stored key order is not the reading order: listed fields
        # first, the rest after.
        first = [k for k in shape["order"] if k in value]
        parts = render({**{k: value[k] for k in first}, **value}, "")
    else:
        parts = render(value, "")
    shown, seen = [], set()
    for part in parts:  # "engineering, engineering" said twice reads once
        if part and part.strip() and part.casefold() not in seen:
            seen.add(part.casefold())
            shown.append(part)
    return shape.get("join", rules["separator"]).join(shown)


def display_text(type_key: Optional[str], value: Any) -> str:
    """The Vault's one-line words for any entry, for readers outside the view
    (path evidence), so a path never shows what the Vault page would not."""
    return _display(vault_catalog().type(type_key) if type_key else None, value, type_key)


def _without(value: Any, fields) -> Any:
    """A record value minus fields that hold the student's own words."""
    if isinstance(value, dict) and fields:
        return {k: v for k, v in value.items() if k not in fields}
    return value


@dataclass
class _Row:
    """An entry plus what the view needs to place and filter it."""
    entry: dict
    section: Optional[str]          # Details section, or None for a story type
    sensitivity: str
    file_ids: set
    capture: Optional[str] = None   # the surface that took it (evidence.capture), never its words


def entry_ref(entry: dict) -> str:
    """An entry named as coverage_areas and profile_cards name it:
    `fact:<key>`, `<record kind>:<id>`, `item:<id>`."""
    if entry["kind"] == "fact":
        return "fact:" + entry["type"]
    return ("item:" if entry["kind"] == "item" else entry["type"] + ":") + str(entry["id"])


class VaultView:
    def __init__(self, db):
        self.db = db
        self.catalog = vault_catalog()
        self.records = StudentRecordService(db)
        self.items = VaultItemService(db)

    # ---- the view ----------------------------------------------------------

    def build(self, workspace_id: str, *, include_sensitive: bool = True,
              now: Optional[datetime] = None, sensitive_types: Iterable[str] = ()) -> dict:
        """`sensitive_types` lets a counselor view show a sensitive type the
        turn needs (spec Access) while every other sensitive type and every
        restricted one stays hidden."""
        copy = view_copy()
        allowed = set(sensitive_types)

        def hidden(type_key: Optional[str], sensitivity: str) -> bool:
            if include_sensitive or sensitivity not in HIDDEN_WHEN_NOT_SENSITIVE:
                return False
            return not (sensitivity == "sensitive" and type_key in allowed)

        issues = self._open_issues(workspace_id)
        files = self._files(workspace_id)
        rows = self._rows(workspace_id, issues, files, _aware(now) or datetime.now(timezone.utc))
        rows = [r for r in rows if not hidden(r.entry["type"], r.sensitivity)]

        details = {s["key"]: {"label": s["label"], "entries": []} for s in copy["sections"]}
        for row in rows:
            if row.section is not None:
                details[row.section]["entries"].append(row.entry)

        story = []
        for spec in self.catalog.types(shown_on="story"):
            if hidden(spec.key, spec.sensitivity):
                continue
            entries = [r.entry for r in rows if r.section is None and r.entry["type"] == spec.key]
            story.append({
                "type": spec.key, "label": spec.label, "entries": entries,
                "rich": (len(entries) >= copy["story_rich_min_entries"]
                         or any(e["level"] == "confirmed" for e in entries)),
                "next_step": (spec.onboarding or {}).get("prompt"),
            })

        cards = [self._card(issue, files, workspace_id) for issue in issues]
        return {
            "details": details,
            "story": story,
            "conflicts": [card for card, sensitivity in cards if sensitivity != NEVER_SHOWN
                          and not hidden(card["type"], sensitivity)],
            "stale": [r.entry for r in rows if r.entry["stale"]],
        }

    def entries_for_document(self, workspace_id: str, file_id: str) -> list[dict]:
        """Every entry this file backs (its own evidence or a corroboration);
        the document's own record is the file itself, not an entry from it."""
        rows = self._rows(workspace_id, self._open_issues(workspace_id), self._files(workspace_id),
                          datetime.now(timezone.utc))
        kind = view_copy()["file_record_kind"]
        return [r.entry for r in rows if file_id in r.file_ids and r.entry["type"] != kind]

    def stale_ids(self, workspace_id: str, now: Optional[datetime] = None) -> set[str]:
        """Entries past their freshness window, named as coverage_areas names
        its sources (`fact:<key>`, `<record kind>:<id>`, `item:<id>`), so the
        completeness meter reads staleness from this one place."""
        rows = self._rows(workspace_id, [], {}, _aware(now) or datetime.now(timezone.utc))
        return {entry_ref(r.entry) for r in rows if r.entry["stale"]}

    def rows(self, workspace_id: str, now: Optional[datetime] = None) -> list[_Row]:
        """Every entry with its sensitivity and capture, documents linked, for
        read models built on the view (the Mirror state card)."""
        return self._rows(workspace_id, self._open_issues(workspace_id), self._files(workspace_id),
                          _aware(now) or datetime.now(timezone.utc))

    # ---- reads -------------------------------------------------------------

    def _open_issues(self, workspace_id: str) -> list[ProfileIssue]:
        return list(self.db.scalars(select(ProfileIssue).where(
            ProfileIssue.workspace_id == workspace_id, ProfileIssue.status == "open")
            .order_by(ProfileIssue.created_at, ProfileIssue.id)))

    def _files(self, workspace_id: str) -> dict[str, str]:
        """file id -> filename for files still in the workspace (not in the trash)."""
        return dict(self.db.execute(select(FileRecord.id, FileRecord.filename).where(
            FileRecord.workspace_id == workspace_id, FileRecord.status == "active")).all())

    def _rows(self, workspace_id: str, issues: list[ProfileIssue], files: dict, now: datetime) -> list[_Row]:
        questioned = set()
        for issue in issues:
            evidence = issue.evidence or {}
            if issue.affected_id:
                questioned.add((issue.affected_type, issue.affected_id))
            if evidence.get("current_fact_id"):
                questioned.add(("vault_fact", evidence["current_fact_id"]))
            if evidence.get("record_type") and evidence.get("record_id"):
                questioned.add((evidence["record_type"], evidence["record_id"]))

        rows: list[_Row] = []
        facts = self.db.scalars(select(VaultFact).where(
            VaultFact.workspace_id == workspace_id, VaultFact.status == "active")
            .order_by(VaultFact.valid_from.desc()))
        seen = set()
        for fact in facts:
            spec = self.catalog.type(fact.field_key)
            if spec is None or spec.storage != "fact" or fact.field_key in seen:
                continue  # the catalog defines what the Vault shows
            seen.add(fact.field_key)
            value = _unwrap(fact.value)
            level = level_of(fact.source_type, None, fact.evidence, value=value,
                             capture_method=fact.capture_method)
            rows.append(self._row(
                spec, "fact", fact.id, value, level, fact.source_type, fact.evidence, files, now,
                observed=[fact.valid_from or fact.created_at],
                confirmed_at=self._confirmed_at(level, fact.evidence),
                in_question=("vault_fact", fact.id) in questioned))

        # Catalog record types, then the kinds vault_view.json places (spec
        # Access: the student sees everything); a kind marked hidden is skipped.
        uncatalogued = view_copy()["uncatalogued_records"]
        kinds = [spec.key for spec in self.catalog.types(storage="record")]
        kinds += [kind for kind, place in uncatalogued.items() if not place.get("hidden")]
        for kind in kinds:
            spec = self.catalog.type(kind)
            for record in self.records.list(workspace_id, kind):
                value = self.records._values(kind, record)
                level = level_of(record.source_type, record.verification_status, record.evidence,
                                 value=value, capture_method=record.capture_method)
                rows.append(self._row(
                    spec, "record", record.id, value, level, record.source_type, record.evidence, files, now,
                    observed=[record.updated_at or record.created_at],
                    confirmed_at=self._confirmed_at(level, record.evidence),
                    in_question=(kind, record.id) in questioned, record_kind=kind))

        for item in self.items.active(workspace_id):
            spec = self.catalog.type(item.item_type)
            if spec is None:
                continue
            sightings = [c.get("observed_at") for c in (item.evidence or {}).get("corroborations", [])]
            rows.append(self._row(
                spec, "item", item.id, item.value, item.level, item.source_type, item.evidence, files, now,
                observed=[item.observed_at or item.created_at, *sightings],
                confirmed_at=_aware(item.confirmed_at) if item.level == "confirmed" else None,
                in_question=item.conflict_state == "in_question" or ("vault_item", item.id) in questioned,
                source_language=item.source_language))
        return rows

    # ---- shaping -----------------------------------------------------------

    def _row(self, spec: Optional[TypeSpec], kind: str, entry_id: str, value: Any, level: str,
             source_type: str, evidence: Optional[dict], files: dict, now: datetime, *, observed: list,
             confirmed_at: Optional[datetime], in_question: bool, record_kind: Optional[str] = None,
             source_language: Optional[str] = None) -> _Row:
        evidence = evidence or {}
        omit = view_copy()["uncatalogued_records"].get(record_kind or "", {}).get("omit_fields", ())
        refs = [evidence, *reversed(evidence.get("corroborations", []))]
        if spec is None:  # a record kind outside the catalog, placed by vault_view.json
            place = view_copy()["uncatalogued_records"][record_kind]
            type_key, label, section, sensitivity, days = (
                record_kind, place["label"], place["section"], place["sensitivity"], None)
            value = _without(value, place.get("omit_fields", ()))
            if place.get("file_field"):
                refs = [{"file_id": value.get(place["file_field"])}, *refs]
        else:
            type_key, label, sensitivity, days = spec.key, spec.label, spec.sensitivity, spec.freshness_days
            section = (spec.section or view_copy()["default_section"]) if spec.shown_on == "details" else None

        moments = [m for m in (_aware(m) for m in [*observed, confirmed_at]) if m]
        fresh_until = max(moments) + timedelta(days=days) if days and moments else None
        entry = {
            "kind": kind, "type": type_key, "id": entry_id, "value": value, "label": label,
            "display": _display(spec, value, type_key), "level": level, "badge": badge_for(level, in_question),
            "source": source_type, "source_language": source_language or evidence.get("source_language"),
            "document": self._link(refs, files),
            "observed_at": _iso(_aware(observed[0])), "confirmed_at": _iso(confirmed_at),
            "fresh_until": _iso(fresh_until), "stale": bool(fresh_until and now > fresh_until),
            "in_question": in_question,
            "disagreements": [{
                "value": shown, "display": _display(spec, shown, type_key),
                "source": d.get("source_type"), "document": self._link([d], files),
            } for d in evidence.get("disagreements", [])
                for shown in [_without(d.get("value"), omit)] if shown not in (None, {})],
        }
        if spec is not None and spec.choice_by_level:
            # The level the editor reads lists by, even for an older row
            # whose title is a wording ("BS Computer Science").
            entry["record_level"] = vault_catalog().record_level(spec, value)
        file_ids = {r.get("file_id") for r in refs if isinstance(r, dict) and r.get("file_id")}
        capture = evidence.get("capture")
        return _Row(entry, section, sensitivity, file_ids, capture if isinstance(capture, str) else None)

    @staticmethod
    def _link(refs: list, files: dict) -> Optional[dict]:
        """The first reference whose file is still in the workspace; null when gone."""
        for ref in refs:
            file_id = (ref or {}).get("file_id")
            if file_id in files:
                return {"file_id": file_id, "page": page_of(ref), "filename": files[file_id]}
        return None

    @staticmethod
    def _confirmed_at(level: str, evidence: Optional[dict]) -> Optional[datetime]:
        if level != "confirmed":
            return None
        return _aware(((evidence or {}).get("confirmation") or {}).get("confirmed_at"))

    def _source(self, level: str, said_on: Any, refs: list, files: dict) -> dict:
        """Where one side of a conflict came from: the entry ladder's level and
        badge, the day it was said or read, and the file behind it. Built from
        named keys only, so a quote on the evidence never reaches the card."""
        return {"level": level, "badge": badge_for(level, False), "said_on": _iso(_aware(said_on)),
                "document": self._link(refs, files)}

    def _saved_source(self, issue: ProfileIssue, form: str, type_key: Optional[str], workspace_id: str,
                      files: dict) -> Optional[dict]:
        """The saved side is the entry the card is about, read from its own store."""
        evidence = issue.evidence or {}
        row = level = said_on = None
        if form == "fact":
            fact_id = evidence.get("current_fact_id") or (
                issue.affected_id if issue.affected_type == "vault_fact" else None)
            row = self.db.get(VaultFact, fact_id) if fact_id else None
            if row is not None and row.workspace_id == workspace_id:
                level = level_of(row.source_type, None, row.evidence, value=_unwrap(row.value),
                                 capture_method=row.capture_method)
                said_on = row.valid_from or row.created_at
        elif form == "record":
            record_id = evidence.get("record_id") or issue.affected_id
            row = self.records.get(workspace_id, type_key, record_id) if (
                record_id and type_key in ENTITY_MODELS) else None
            if row is not None:
                level = level_of(row.source_type, row.verification_status, row.evidence,
                                 value=self.records._values(type_key, row), capture_method=row.capture_method)
                said_on = row.updated_at or row.created_at
        elif form == "item" and issue.affected_id:
            row = self.db.get(VaultItem, issue.affected_id)
            if row is not None and row.workspace_id == workspace_id:
                level, said_on = row.level, row.observed_at or row.created_at
        if level is None:
            return None
        row_evidence = row.evidence or {}
        return self._source(level, said_on, [row_evidence, *reversed(row_evidence.get("corroborations", []))], files)

    def _proposed_source(self, issue: ProfileIssue, form: str, proposed: Any, workspace_id: str,
                         files: dict) -> Optional[dict]:
        """The new side is the proposal the card asks about: the source the
        writer recorded on the card, else the proposing candidate."""
        evidence = issue.evidence or {}
        if form == "document_owner":
            return self._source("shown", issue.created_at, [evidence], files)
        candidate = self.db.get(MemoryCandidate, issue.candidate_id) if issue.candidate_id else None
        if candidate is not None and candidate.workspace_id != workspace_id:
            candidate = None
        said_on = candidate.created_at if candidate is not None else issue.created_at
        recorded = evidence.get("proposed_source")
        if isinstance(recorded, dict) and recorded.get("level"):  # an item card
            return self._source(recorded["level"], recorded.get("observed_at") or said_on, [recorded], files)
        if evidence.get("proposed_source_type"):
            source_type, proposal = evidence["proposed_source_type"], evidence.get("proposed_evidence")
        elif candidate is not None:
            source_type, proposal = candidate.source_type, candidate.evidence
        else:
            return None
        return self._source(level_of(source_type, None, proposal, value=proposed), said_on, [proposal], files)

    def _card(self, issue: ProfileIssue, files: dict, workspace_id: str) -> tuple[dict, str]:
        """One conflict card (short English copy and the two values, never evidence)
        and the sensitivity that decides whether a counselor view shows it."""
        copy = view_copy()
        evidence = issue.evidence or {}
        if issue.issue_type == "document_owner":
            form, type_key = "document_owner", None
            current, proposed = evidence.get("vault_names"), evidence.get("document_names")
        elif issue.affected_type == "vault_item" or evidence.get("item_type"):
            form, type_key = "item", evidence.get("item_type")
            current, proposed = evidence.get("current_value"), evidence.get("proposed_value")
        elif evidence.get("field_key"):
            form, type_key = "fact", evidence.get("field_key")
            current, proposed = evidence.get("current_value"), evidence.get("proposed_value")
        elif evidence.get("record_type"):
            form, type_key = "record", evidence.get("record_type")
            current, proposed = evidence.get("current"), evidence.get("proposed")
        else:
            form, type_key, current, proposed = "other", None, None, None

        spec = self.catalog.type(type_key) if type_key else None
        place = copy["uncatalogued_records"].get(type_key) if spec is None and type_key else None
        words = copy["conflict_copy"][form]
        label = (spec.label if spec else (place or {}).get("label")
                 or (type_key or "entry").replace("_", " ").replace(".", " ")).lower()
        filename = files.get(evidence.get("file_id")) or evidence.get("filename") or "this document"
        if place and place.get("omit_fields"):
            current, proposed = _without(current, place["omit_fields"]), _without(proposed, place["omit_fields"])
        if issue.issue_type in copy["answers"]:
            answers = copy["answers"][issue.issue_type]
        elif current is None and form in ("item", "fact", "record"):
            # Nothing is saved yet (a future-dated change, a possible new
            # record): there is no current value to keep.
            answers = copy["answers"]["no_current_value"]
        else:
            answers = copy["answers"]["default"]
        if spec is not None:
            sensitivity = spec.sensitivity
        elif place is not None:
            sensitivity = NEVER_SHOWN if place.get("hidden") else place["sensitivity"]
        elif type_key:
            sensitivity = "restricted"  # not in the catalog: withheld unless everything is shown
        else:
            sensitivity = words.get("sensitivity", "normal")
        return {
            "id": issue.id, "kind": form, "type": type_key, "entry_id": issue.affected_id,
            "summary": words["summary"].format(label=label, filename=filename),
            "question": words["question"].format(label=label, filename=filename),
            "current": current, "proposed": proposed,
            "current_display": _display(spec, current, type_key), "proposed_display": _display(spec, proposed, type_key),
            "answers": list(answers),
            "current_source": self._saved_source(issue, form, type_key, workspace_id, files),
            "proposed_source": self._proposed_source(issue, form, proposed, workspace_id, files),
            "created_at": _iso(_aware(issue.created_at)),
        }, sensitivity
