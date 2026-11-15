"""Admission modes as a data vocabulary (ADR-001 D3; master R-38).

The modes, what each means, which calendar date fields and registry links its steps use, live in
`admission_modes.yaml`. A system's mode is a Knowledge fact on its `admission_system` row; `check_mode_fact` is the one
rule the import applies to such a fact. Nothing here names a region, a body or a portal (R-58)."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from app.os import models
from app.os.knowledge.fact_classes import classes, deciding_level, fact_class
from app.os.registry.calendars import calendar_types
from app.os.registry.model import ALLOWED_PARENTS, KINDS

MODES_FILE = Path(__file__).with_name("admission_modes.yaml")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class AdmissionModeError(ValueError):
    pass


@dataclass(frozen=True)
class AdmissionMode:
    key: str
    label: str
    description: str
    calendars: dict[str, tuple[str, ...]]  # calendar type -> the date fields the mode's steps may read
    calendar_of: str  # the registry kind whose calendar holds those dates
    links: tuple[str, ...]  # registry link rels from the system that the mode's steps rely on


@dataclass(frozen=True)
class Vocabulary:
    field: str  # the Knowledge field that holds a system's mode
    entity_kind: str  # the registry kind a mode fact may sit on
    requires: str  # the trust level the mode fact needs before a step it gates is firm (D3)
    modes: dict[str, AdmissionMode]


def _fail(msg: str) -> None:
    raise AdmissionModeError(f"{MODES_FILE.name}: {msg}")


def parse(data: dict) -> Vocabulary:
    """Validates a vocabulary document; raises AdmissionModeError naming the first bad entry."""
    if not isinstance(data, dict) or data.get("version") != 1:
        _fail("needs `version: 1`")
    field, kind, requires = data.get("field"), data.get("entity_kind"), data.get("requires")
    if not isinstance(field, str) or not field:
        _fail("needs `field`, the Knowledge field of a system's mode")
    if kind not in KINDS:
        _fail(f"entity_kind '{kind}' is not a registry kind")
    if fact_class(field) not in classes() or fact_class(field) == "unclassified":
        _fail(f"field '{field}' is not listed in fact_classes.yaml `fields`")
    if requires != deciding_level(field):
        _fail(f"requires '{requires}' but fact_classes.yaml `decides_at` gives '{deciding_level(field)}' for '{field}'")
    blocks = data.get("modes")
    if not isinstance(blocks, dict) or not blocks:
        _fail("needs at least one mode")
    ctypes = calendar_types()
    calendar_owners = ALLOWED_PARENTS["calendar"]
    modes: dict[str, AdmissionMode] = {}
    for key, block in blocks.items():
        where = f"mode {key}"
        if not isinstance(key, str) or not _KEY.match(key):
            _fail(f"{where}: a mode key is a snake case slug")
        if not isinstance(block, dict):
            _fail(f"{where}: needs label, description, calendars, calendar_of and links")
        unknown = sorted(set(block) - {"label", "description", "calendars", "calendar_of", "links"})
        if unknown:
            _fail(f"{where}: unknown keys {unknown}")
        for text in ("label", "description"):
            if not isinstance(block.get(text), str) or not block[text].strip():
                _fail(f"{where}: needs a {text}")
        cals = block.get("calendars")
        if not isinstance(cals, dict):
            _fail(f"{where}: `calendars` maps a calendar type to its date fields")
        for ctype, fields in cals.items():
            if ctype not in ctypes:
                _fail(f"{where}: unknown calendar type '{ctype}' (use one of {sorted(ctypes)})")
            if not isinstance(fields, list) or not fields:
                _fail(f"{where}: calendar '{ctype}' needs its date fields as a list")
            bad = sorted(f for f in fields if f not in ctypes[ctype].fields)
            if bad:
                _fail(f"{where}: {bad} are not dates of a {ctype} calendar ({sorted(ctypes[ctype].fields)})")
        if block.get("calendar_of") not in calendar_owners:
            _fail(f"{where}: calendar_of '{block.get('calendar_of')}' cannot hold a calendar "
                  f"(use one of {list(calendar_owners)})")
        links = block.get("links")
        if not isinstance(links, list):
            _fail(f"{where}: `links` is a list of registry link rels")
        bad = sorted(rel for rel in links if rel not in models.REGISTRY_LINK_RELS)
        if bad:
            _fail(f"{where}: unknown link rels {bad} (use {list(models.REGISTRY_LINK_RELS)})")
        modes[key] = AdmissionMode(key, block["label"].strip(), " ".join(block["description"].split()),
                                   {c: tuple(f) for c, f in cals.items()}, block["calendar_of"], tuple(links))
    return Vocabulary(field, kind, requires, modes)


@cache
def _load(path: Path = MODES_FILE) -> Vocabulary:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))


def vocabulary() -> Vocabulary:
    return _load()


def admission_modes() -> dict[str, AdmissionMode]:
    return dict(_load().modes)


def check_mode_fact(field: str, value: object, entity_kind: str | None) -> tuple[str, str] | None:
    """The import's rule for a fact (ADR-001 D3): None when the field is not the mode field or the fact is valid; else
    (reason, detail). A mode fact sits only on an entity of the vocabulary's kind and names one of its modes."""
    v = _load()
    if field != v.field:
        return None
    if entity_kind != v.entity_kind:
        what = f"a {entity_kind}" if entity_kind else "a programme or an entity of unknown kind"
        return "mode_on_wrong_kind", f"'{field}' is a fact of an {v.entity_kind}, not of {what}"
    if not isinstance(value, str) or value not in v.modes:
        return "unknown_admission_mode", f"'{value}' is not an admission mode (use one of {sorted(v.modes)})"
    return None
