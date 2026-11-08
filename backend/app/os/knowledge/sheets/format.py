"""The research spreadsheet format and its vocabularies, loaded from `format.yaml` (P2 spec §4.6; master R-67)."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

HERE = Path(__file__).parent
FORMAT_FILE = HERE / "format.yaml"
LEGACY_DIR = HERE / "legacy"


def _fill(m: re.Match, template: str) -> str:
    return re.sub(r"\{(\d)\}", lambda g: m.group(int(g.group(1))), template)


@dataclass(frozen=True)
class SheetSpec:
    name: str
    key: str
    required: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Layout:
    """An older Programmes layout and how it becomes canonical rows (R-67)."""

    name: str
    sheet: str
    detect: tuple[str, ...]
    emit: tuple[dict, ...]
    note_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class Format:
    raw: dict
    sheets: dict[str, SheetSpec]
    checker_columns: tuple[str, ...]
    claude_statuses: tuple[str, ...]
    check1_results: tuple[str, ...]
    check2_values: dict[str, str]
    layouts: tuple[Layout, ...]

    def all_columns(self, sheet: str) -> tuple[str, ...]:
        return self.sheets[sheet].columns + self.checker_columns

    def read_method(self, text: str | None) -> str | None:
        """The Knowledge read method of a free-text one, or None when it maps to none."""
        t = (text or "").strip().lower()
        for rule in self.raw["read_methods"]:
            if re.search(rule["match"], t):
                return rule["method"]
        return None

    @property
    def needs_refetch(self) -> tuple[str, ...]:
        return tuple(self.raw["needs_refetch"])

    def is_lead_read(self, text: str | None) -> bool:
        return (text or "").strip().lower() in {s.lower() for s in self.raw["lead_read_methods"]}

    def not_official_type(self, source_type: str | None) -> bool:
        t = (source_type or "").strip().lower()
        return t in {s.lower() for s in self.raw["source_types"]["not_official"]}

    def not_official_host(self, host: str) -> bool:
        host = host.lower()
        return any(host == h or host.endswith("." + h) for h in self.raw["not_official_hosts"])

    def out_of_scope_region(self, text: str | None) -> bool:
        t = (text or "").strip().lower()
        return t in {r.lower() for r in self.raw["out_of_scope_regions"]}

    def kind_of_type(self, type_text: str | None) -> str | None:
        t = (type_text or "").strip().lower()
        for kind, types in self.raw["type_kinds"].items():
            if t in types:
                return kind
        return None

    def intake(self, text: str | None) -> tuple[str, int] | None:
        """(term, year) of an intake text, or None when no rule matches."""
        t = (text or "").strip().lower()
        for rule in self.raw["intake_patterns"]:
            m = re.match(rule["regex"], t)
            if m:
                return _fill(m, rule["term"]), int(_fill(m, rule["year"]))
        return None

    def owner_accepted_ref(self, which: int, name: str | None) -> str | None:
        """`claude_check_1` / `claude_check_2` for the names the owner-accepted import knows, else None."""
        for ref, names in self.raw["owner_accepted"][f"checker{which}"].items():
            if (name or "").strip() in names:
                return ref
        return None


@cache
def load_format(path: Path = FORMAT_FILE, legacy_dir: Path = LEGACY_DIR) -> Format:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sheets = {n: SheetSpec(n, s["key"], tuple(s["required"]), tuple(s["columns"])) for n, s in raw["sheets"].items()}
    for s in sheets.values():
        if not set(s.required) <= set(s.columns):
            raise ValueError(f"sheet {s.name}: required columns must be columns")
    layouts = []
    for f in sorted(legacy_dir.glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        layouts.append(Layout(d["layout"], d["sheet"], tuple(d["detect"]), tuple(d["emit"]),
                              tuple(d.get("note_from") or ())))
    return Format(raw, sheets, tuple(raw["checker_columns"]), tuple(raw["claude_statuses"]),
                  tuple(raw["check1_results"]), dict(raw["check2_values"]), tuple(layouts))
