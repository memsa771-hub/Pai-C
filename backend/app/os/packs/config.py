"""The application pack as route data (Slice 6a spec S6a-D2, D4, D6, D12).

Per route, one YAML file: the data-sheet fields and where each value comes from, the default checklist, the format
rules for files, the step-by-step instructions per application route, and the fees to show. Python knows only the
generic item kinds (`document`, `statement`, `entered`, `manual`); every name, list and number is in the YAML.
"""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PACK_DIR = Path(__file__).parent
ENTERED = "entered"
STATEMENT_KINDS = ("sop", "cv")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_KEY = r"^[a-z][a-z0-9_]*$"


class PackConfigError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SheetField(_Model):
    key: str = Field(pattern=_KEY)
    label: str
    source: str  # a confirmed profile key ("<doc_type>.<field>"), or "entered": the student types it
    required: bool = False
    hint: str = ""


class Section(_Model):
    title: str
    fields: list[SheetField] = Field(min_length=1)


class Item(_Model):
    key: str = Field(pattern=_KEY)
    label: str
    kind: Literal["document", "statement", "entered", "manual"]
    ref: str | None = None  # document: a document type; statement: sop | cv; entered: a data-sheet field key
    format: str | None = None  # a named format; the route default otherwise
    note: str | None = None

    @model_validator(mode="after")
    def _ref(self) -> "Item":
        if (self.kind == "manual") != (self.ref is None):
            raise ValueError(f"item '{self.key}': a {self.kind} item {'has no' if self.kind == 'manual' else 'needs a'} ref")
        return self


class Format(_Model):
    types: list[Literal["pdf"]] = ["pdf"]
    max_mb: float = Field(gt=0)
    colour: bool = False
    notes: list[str] = []  # what the renderer cannot fix, e.g. "an attested copy": the student confirms it


class Formats(_Model):
    default: Format
    named: dict[str, Format] = {}


class Step(_Model):
    text: str  # {fact} and {constant} placeholders are filled from the programme's facts and the playbook
    source: str  # "fact:<name>" (that fact's page) or "citation:<playbook source id>"


class FeeRef(_Model):
    label: str
    source: str  # "fact:<name>" or "constant:<name>"


class PackConfig(_Model):
    route_key: str
    version: int = Field(ge=1)
    data_sheet: list[Section] = Field(min_length=1)
    checklist: list[Item] = Field(min_length=1)
    formats: Formats
    instructions: dict[str, list[Step]] = Field(min_length=1)  # keyed by the route's application_route values
    fees: list[FeeRef] = []

    @model_validator(mode="after")
    def _unique(self) -> "PackConfig":
        for name, keys in (("data-sheet field", [f.key for s in self.data_sheet for f in s.fields]),
                           ("checklist item", [i.key for i in self.checklist])):
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            if dupes:
                raise ValueError(f"duplicate {name} keys {dupes}")
        return self

    def fields(self) -> list[SheetField]:
        return [f for s in self.data_sheet for f in s.fields]

    def format_for(self, item: Item) -> Format:
        return self.formats.named[item.format] if item.format else self.formats.default


def load_pack_config(path: Path) -> PackConfig:
    try:
        return PackConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as e:
        raise PackConfigError(f"{path.name}: invalid YAML: {e}") from e
    except ValidationError as e:
        raise PackConfigError(f"{path.name}: {e}") from e


def load_pack_configs(directory: Path = PACK_DIR) -> dict[str, PackConfig]:
    out: dict[str, PackConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        cfg = load_pack_config(path)
        if cfg.route_key in out:
            raise PackConfigError(f"{path.name}: a second pack config for route {cfg.route_key}")
        out[cfg.route_key] = cfg
    return out


def _citations(book) -> set[str]:
    return ({c.source for t in book.tasks for c in t.citations}
            | {c.source for k in book.constants.values() for c in k.citations})


def check_pack_config(cfg: PackConfig, profile_keys: set[str], doc_types: set[str], book, profile) -> None:
    """Every profile key, document type, statement kind, entered field, format, route value, fact, constant and
    citation the config names must exist. `profile` is the route's research profile, or None when the route has none
    (then route values and facts are not checked, as for eligibility rules). Raises PackConfigError naming them."""
    where = f"pack for {cfg.route_key}"

    def fail(what: str) -> None:
        raise PackConfigError(f"{where}: {what}")

    if book.key != cfg.route_key:
        fail(f"route '{cfg.route_key}' has no playbook")
    entered = {f.key for f in cfg.fields() if f.source == ENTERED}
    for f in cfg.fields():
        if f.source != ENTERED and f.source not in profile_keys:
            fail(f"data-sheet field '{f.key}': unknown profile key '{f.source}'")
    for i in cfg.checklist:
        if i.kind == "document" and i.ref not in doc_types:
            fail(f"checklist item '{i.key}': unknown document type '{i.ref}'")
        if i.kind == "statement" and i.ref not in STATEMENT_KINDS:
            fail(f"checklist item '{i.key}': unknown statement kind '{i.ref}'")
        if i.kind == "entered" and i.ref not in entered:
            fail(f"checklist item '{i.key}': '{i.ref}' is not an entered data-sheet field")
        if i.format and i.format not in cfg.formats.named:
            fail(f"checklist item '{i.key}': unknown format '{i.format}'")
    facts = {f.name for f in profile.fields} if profile is not None else None
    constants, citations = set(book.constants), _citations(book)
    if profile is not None:
        route_values = set(next((f.values for f in profile.fields if f.name == "application_route"), {}))
        unknown = sorted(set(cfg.instructions) - route_values)
        if unknown:
            fail(f"instructions for unknown application routes {unknown}")

    def check_source(source: str, what: str, kinds: tuple[str, ...]) -> None:
        kind, _, name = source.partition(":")
        if kind not in kinds or not name:
            fail(f"{what}: source '{source}' must be one of {[k + ':<name>' for k in kinds]}")
        known = {"fact": facts, "constant": constants, "citation": citations}[kind]
        if known is not None and name not in known:
            fail(f"{what}: unknown {kind} '{name}'")

    for route_value, steps in cfg.instructions.items():
        for n, step in enumerate(steps, 1):
            what = f"instructions '{route_value}' step {n}"
            check_source(step.source, what, ("fact", "citation"))
            for name in _PLACEHOLDER.findall(step.text):  # without a research profile, facts are not known here
                if facts is not None and name not in facts and name not in constants:
                    fail(f"{what}: unknown placeholder '{{{name}}}'")
    for fee in cfg.fees:
        check_source(fee.source, f"fee '{fee.label}'", ("fact", "constant"))


def load_checked_pack_configs(directory: Path, doc_types, books, profiles) -> dict[str, PackConfig]:
    """Every pack config in `directory`, checked against the document types, the newest playbook of its route and
    the route's research profile (if any). An invalid config, or one for a route with no playbook, stops startup."""
    from app.os.eligibility.rules import profile_keys  # imported here: eligibility is a sibling module

    keys = profile_keys(doc_types)
    newest = {}
    for (key, version), b in books.items():
        if key not in newest or version > newest[key].version:
            newest[key] = b
    configs = load_pack_configs(directory)
    for cfg in configs.values():
        if cfg.route_key not in newest:
            raise PackConfigError(f"pack for {cfg.route_key}: no playbook for this route")
        profile = next((p for p in profiles.values() if p.route_key == cfg.route_key), None)
        check_pack_config(cfg, keys, set(doc_types), newest[cfg.route_key], profile)
    return configs
