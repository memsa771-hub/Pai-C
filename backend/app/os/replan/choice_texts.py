"""Student sentences for a choice change that went to the Counsellor (P1-T6). They live in choice_texts.yaml, which is
stored `approved: false` until the owner approves them: until then they are returned only in rehearsal mode."""

from functools import cache
from pathlib import Path

import yaml

PATH = Path(__file__).parent / "texts" / "choice_texts.yaml"
KEYS = ("requested", "expired")


@cache
def _load(path: Path) -> tuple[bool, dict[str, str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in KEYS if not isinstance(raw.get(k), str) or not raw[k].strip()]
    if missing:
        raise ValueError(f"{path.name}: no sentence for {', '.join(missing)}")
    return raw.get("approved") is True, {k: raw[k].strip() for k in KEYS}


def note(key: str, settings, path: Path = PATH) -> str | None:
    """The sentence for `key`, or None while the file is not approved and the OS is not in rehearsal mode."""
    approved, texts = _load(path)
    if not (approved or getattr(settings, "rehearsal", False)):
        return None
    return texts.get(key)
