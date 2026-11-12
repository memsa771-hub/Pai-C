"""The launch gate's expected fields, from `expected.yaml` (P2-T9). Nothing about a family is written in code."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

FILE = Path(__file__).with_name("expected.yaml")


@dataclass(frozen=True)
class Expected:
    floor_fields: tuple[str, ...]
    institution_types: tuple[str, ...]
    floor_classes: tuple[str, ...]


@cache
def _load(path: Path = FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def for_family(family: str) -> Expected:
    data = _load()
    block = {**data["default"], **(data.get("families") or {}).get(family, {})}
    return Expected(tuple(block["floor_fields"]), tuple(block.get("institution_types") or ()),
                    tuple(block["floor_classes"]))


def settings() -> dict:
    d = _load()
    return {"checks_per_fact": int(d["checks_per_fact"]), "work_hours_per_day": float(d["work_hours_per_day"]),
            "measure_days": int(d["measure_days"])}

