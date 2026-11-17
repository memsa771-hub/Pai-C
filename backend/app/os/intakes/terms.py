"""Intake term codes as data (P2-D5, R-62). Nothing about a term is written in code."""

import re
from functools import cache
from pathlib import Path

import yaml

TERMS_FILE = Path(__file__).with_name("terms.yaml")
_CODE = re.compile(r"[a-z_]+")


class UnknownTerm(ValueError):
    pass


@cache
def _load(path: Path = TERMS_FILE) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for item in data["terms"]:
        code = item["code"]
        if not _CODE.fullmatch(code) or code in out:
            raise ValueError(f"{path.name}: bad or duplicate term code '{code}'")
        out[code] = item["label"]
    return out


def terms() -> dict[str, str]:
    """Term code -> label."""
    return dict(_load())


def check_term(code: str, extra: tuple[str, ...] | list[str] = ()) -> str:
    """The code, if it is in the data file or among `extra` (the terms a playbook declares); else UnknownTerm."""
    if code in _load() or code in extra:
        return code
    raise UnknownTerm(f"unknown intake term '{code}'")
