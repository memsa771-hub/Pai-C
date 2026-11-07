"""Fact classes and the high-stakes flag (P2 spec P2-D7, master R-25, §8.2). The classes and the field → class map
are data (`fact_classes.yaml`). A field that is not listed is `unclassified`, which is high-stakes (fail safe)."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

CLASSES_FILE = Path(__file__).with_name("fact_classes.yaml")
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class FactClass:
    key: str
    high_stakes: bool
    label: str


@cache
def _load(path: Path = CLASSES_FILE) -> tuple[dict[str, FactClass], dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cls = {k: FactClass(k, bool(v["high_stakes"]), v["label"]) for k, v in data["classes"].items()}
    if UNCLASSIFIED not in cls or not cls[UNCLASSIFIED].high_stakes:
        raise ValueError(f"'{UNCLASSIFIED}' must be listed and high-stakes")
    fields = dict(data.get("fields") or {})
    unknown = sorted({c for c in fields.values() if c not in cls})
    if unknown:
        raise ValueError(f"fields name unknown classes: {unknown}")
    return cls, fields


def classes() -> dict[str, FactClass]:
    return dict(_load()[0])


def fact_class(field: str, explicit: str | None = None) -> str:
    """The class of a fact: its own `fact_class` when set, else its field's class, else `unclassified`."""
    cls, fields = _load()
    if explicit is not None:
        if explicit not in cls:
            raise ValueError(f"unknown fact class '{explicit}'")
        return explicit
    return fields.get(field, UNCLASSIFIED)


def is_high_stakes(cls: str) -> bool:
    return _load()[0][cls].high_stakes
