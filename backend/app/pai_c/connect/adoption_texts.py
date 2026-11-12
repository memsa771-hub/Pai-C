"""The student sentences for adopting a self-serve plan (adoption_texts.yaml, R-08). The texts live in the YAML file,
never in code. While `approved` is false they are returned only in rehearsal (`config.CONNECT_CONSENT_DRAFT`), else
`None`. Import fails when a sentence is missing."""

from pathlib import Path

import yaml

from app.config import config

TEXTS_PATH = Path(__file__).with_name("adoption_texts.yaml")
KEYS = ("offer", "agree", "choose_field_first", "too_many_places", "linking")


def _load() -> dict:
    raw = yaml.safe_load(TEXTS_PATH.read_text(encoding="utf-8")) or {}
    missing = [k for k in KEYS if not isinstance(raw.get(k), str) or not raw[k].strip()]
    if missing:
        raise ValueError(f"{TEXTS_PATH.name}: no text for {', '.join(missing)}")
    return raw


_RAW = _load()


def _usable() -> bool:
    return bool(_RAW.get("approved")) or bool(config.CONNECT_CONSENT_DRAFT)


def texts() -> dict | None:
    """All the adoption sentences, `{offer, agree, choose_field_first, too_many_places, linking}`; None while the file
    is not approved."""
    return {k: _RAW[k].strip() for k in KEYS} if _usable() else None
