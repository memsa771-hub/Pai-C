"""The sentences the OS shows a student about the requests in their plan (P1-T8, D-w16). They live in `texts.yaml`
(approved by the owner). A missing key or a file not approved stops startup, not a request."""

from pathlib import Path

import yaml

PATH = Path(__file__).with_name("texts.yaml")
KEYS = ("how_stated", "how_shown", "how_confirmed", "how_document", "how_which_is_right", "how_impossible",
        "answer_required", "current_label", "proposed_label", "proposed_said_label", "new_label", "unanswered_swap", "unanswered_drop",
        "unanswered_all", "unanswered_proposed", "answer_changed")


def load(path: Path = PATH) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("approved") is not True:
        raise ValueError(f"{path.name} is not approved by the owner")
    texts = raw.get("texts") or {}
    missing = [k for k in KEYS if not isinstance(texts.get(k), str) or not texts[k].strip()]
    if missing:
        raise ValueError(f"{path.name} misses: {', '.join(missing)}")
    return {k: texts[k] for k in KEYS}


_TEXTS = load()  # at import: a missing key fails here


def text(key: str) -> str:
    return _TEXTS[key]


def how(kind: str, need_kind: str, evidence: str, impossible: bool = False) -> str:
    """The sentence that tells the student how a request closes."""
    if kind == "which_is_right":
        return _TEXTS["how_impossible" if impossible else "how_which_is_right"]
    return _TEXTS["how_document" if need_kind == "document" else f"how_{evidence}"]
