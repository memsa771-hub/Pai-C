"""The region vocabulary (master R-76, P2 spec §4.1). The codes, names and accepted spellings are data
(`regions.yaml`); no region or country name is written in code (R-58)."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

REGIONS_FILE = Path(__file__).with_name("regions.yaml")


class UnknownRegion(ValueError):
    pass


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    aliases: tuple[str, ...]


def _fold(text: str) -> str:
    """Case, spaces, hyphens, underscores, dots and '&' / 'and' do not change a spelling."""
    t = text.strip().lower().replace("&", " and ")
    t = re.sub(r"[\s\-_.,]+", " ", t)
    return re.sub(r"\band\b", "", t).replace(" ", "")


@cache
def _load(path: Path = REGIONS_FILE) -> dict[str, tuple[Region, ...]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, tuple[Region, ...]] = {}
    for country, block in data["countries"].items():
        regions = tuple(Region(r["code"], r["name"], tuple(r.get("aliases") or ())) for r in block["regions"])
        seen: dict[str, str] = {}
        for r in regions:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", r.code):
                raise ValueError(f"region code '{r.code}' must be snake case")
            for spelling in (r.code, r.name, *r.aliases):
                key = _fold(spelling)
                if seen.setdefault(key, r.code) != r.code:
                    raise ValueError(f"spelling '{spelling}' names two regions")
        out[country] = regions
    return out


def countries() -> list[str]:
    return sorted(_load())


def regions(country: str) -> list[Region]:
    try:
        return list(_load()[country])
    except KeyError:
        raise UnknownRegion(f"no region vocabulary for country '{country}'") from None


def normalise_region(text: str, country: str) -> str:
    """The region code for a spelling the vocabulary accepts; anything else is rejected, never guessed."""
    key = _fold(text)
    for r in regions(country):
        if key in {_fold(s) for s in (r.code, r.name, *r.aliases)}:
            return r.code
    raise UnknownRegion(f"unknown region spelling '{text}'")
