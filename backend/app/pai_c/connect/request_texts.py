"""The roadmap's line for a step that waits for the student's data (request_texts.yaml, P1-T8 D-w16). The sentences live
in the YAML file, never in code. A missing key or a file not approved stops startup, not a request."""

from pathlib import Path

import yaml

PATH = Path(__file__).with_name("request_texts.yaml")
KEYS = ("provide_stated", "provide_shown", "provide_confirmed", "which_is_right", "result_expected")


def load(path: Path = PATH) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("approved") is not True:
        raise ValueError(f"{path.name} is not approved by the owner")
    texts = raw.get("texts") or {}
    missing = [k for k in KEYS if not isinstance(texts.get(k), str) or not texts[k].strip()]
    if missing:
        raise ValueError(f"{path.name} misses: {', '.join(missing)}")
    return {k: texts[k].strip() for k in KEYS}


_TEXTS = load()  # at import: a missing key fails here


def text(key: str) -> str:
    return _TEXTS[key]


def line_for(template: str, evidence: str | None = None) -> str | None:
    """The line for a request step's template (`provide`, `which_is_right`, `result_expected`) and evidence level; None
    for any other step."""
    if template == "provide" and evidence in ("stated", "shown", "confirmed"):
        return _TEXTS[f"provide_{evidence}"]
    if template in ("which_is_right", "result_expected"):
        return _TEXTS[template]
    return None
