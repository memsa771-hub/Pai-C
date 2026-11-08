"""Merit formula and closing-merit fact shapes (P2 spec P2-D26, §4.10; master R-31). Pure: no database.

A formula is a fact of field `merit_formula` (class `merit_formula`); a past closing merit is a fact of field
`closing_merit`. When the value depends on a seat category the field carries the category's slug as a suffix
(`merit_formula_<slug>`), because a fact is keyed by field. Both classes are high-stakes: a value is shown as fact only
when `verified` (knowledge/display.py).

Reserved names (M7): every field that equals `merit_formula` or `closing_merit`, or starts with `merit_formula_` or
`closing_merit_`, is a merit field. Its value must have the shape below, and nothing else may use these names."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

UNRECORDED_TERM = "unrecorded"  # IntakeRef needs a term: a fact whose term was never recorded says so, it is not guessed
MERIT_FILE = Path(__file__).with_name("merit.yaml")


class MeritShapeError(ValueError):
    pass


@cache
def _config() -> dict:
    return yaml.safe_load(MERIT_FILE.read_text(encoding="utf-8"))


def intake_year_floor() -> int:
    """The earliest year an IntakeRef can name, read from the contract itself (not written again here)."""
    from annotated_types import Ge

    from app.os.contracts.route_contract import IntakeRef

    return next(m.ge for m in IntakeRef.model_fields["year"].metadata if isinstance(m, Ge))


def term_of(recorded: str) -> str:
    """The term to print for a fact: its own, or `unrecorded` when it never had one."""
    return recorded or UNRECORDED_TERM


def history_years() -> int:
    return int(_config()["history_years"])


def formula_field() -> str:
    return _config()["fields"]["formula"]


def closing_field() -> str:
    return _config()["fields"]["closing"]


def slug(category: str) -> str:
    """A seat category's registry id as a field suffix: lowercase letters, digits and underscores."""
    s = re.sub(r"[^a-z0-9]+", "_", category.strip().lower()).strip("_")
    if not s:
        raise MeritShapeError("empty category")
    return s


def field_for(base: str, category: str | None) -> str:
    return base if not category else f"{base}_{slug(category)}"


def is_merit_field(field: str) -> str | None:
    """'formula' or 'closing' when `field` is one of the merit fields (with or without a category suffix)."""
    for kind, base in (("formula", formula_field()), ("closing", closing_field())):
        if field == base or field.startswith(base + "_"):
            return kind
    return None


@dataclass(frozen=True)
class FormulaPart:
    name: str
    marks_part: str  # the Vault fact key of the marks obtained
    weight: float


@dataclass(frozen=True)
class FormulaValue:
    parts: tuple[FormulaPart, ...]
    total: float


@dataclass(frozen=True)
class ClosingValue:
    value: float
    list_number: int | None
    list_complete: bool


def _num(x, label: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise MeritShapeError(f"{label} must be a number")
    return float(x)


def parse_formula(value) -> FormulaValue:
    """`{parts: [{name, marks_part, weight}], total}`; weights add up to 1; names are unique."""
    if not isinstance(value, dict) or set(value) != {"parts", "total"}:
        raise MeritShapeError("a merit formula is {parts, total}")
    total = _num(value["total"], "total")
    if total <= 0:
        raise MeritShapeError("total must be above 0")
    raw = value["parts"]
    if not isinstance(raw, list) or not raw:
        raise MeritShapeError("a merit formula needs parts")
    parts = []
    for p in raw:
        if not isinstance(p, dict) or set(p) != {"name", "marks_part", "weight"}:
            raise MeritShapeError("a part is {name, marks_part, weight}")
        name, key = p["name"], p["marks_part"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise MeritShapeError("a part name is lowercase letters, digits and underscores")
        if not isinstance(key, str) or not key.strip():
            raise MeritShapeError(f"part {name}: marks_part names a Vault fact key")
        weight = _num(p["weight"], f"part {name} weight")
        if not 0 < weight <= 1:
            raise MeritShapeError(f"part {name}: weight must be above 0 and at most 1")
        parts.append(FormulaPart(name, key, weight))
    if len({p.name for p in parts}) != len(parts):
        raise MeritShapeError("duplicate part")
    if abs(sum(p.weight for p in parts) - 1.0) > 1e-6:
        raise MeritShapeError("part weights must add up to 1")
    return FormulaValue(tuple(parts), total)


def parse_closing(value) -> ClosingValue:
    """`{value, list_number, list_complete}`. A list that is not complete must name its number: the value is then
    "lowest on list N", never the closing merit (R-31)."""
    if not isinstance(value, dict) or set(value) != {"value", "list_number", "list_complete"}:
        raise MeritShapeError("a closing merit is {value, list_number, list_complete}")
    merit = _num(value["value"], "value")
    complete, number = value["list_complete"], value["list_number"]
    if not isinstance(complete, bool):
        raise MeritShapeError("list_complete must be true or false")
    if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 1):
        raise MeritShapeError("list_number must be a whole number from 1")
    if not complete and number is None:
        raise MeritShapeError("a list that is not complete must name its list_number")
    return ClosingValue(merit, number, complete)


def check_value(field: str, value) -> None:
    """Refuses a merit fact whose value has the wrong shape; other fields pass. Used before a fact is stored."""
    kind = is_merit_field(field)
    if kind == "formula":
        parse_formula(value)
    elif kind == "closing":
        parse_closing(value)
