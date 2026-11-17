"""The sentences the OS shows a connected student about uploads (P1-T7, D-y15). They live in `connect_texts.yaml`
(approved by the owner). A missing key stops startup, not a request."""

from pathlib import Path

import yaml

PATH = Path(__file__).with_name("connect_texts.yaml")
KEYS = ("use_documents_page", "vault_differs")


def _load() -> dict[str, str]:
    raw = yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}
    if raw.get("approved") is not True:
        raise ValueError("connect_texts.yaml is not approved by the owner")
    texts = raw.get("texts") or {}
    missing = [k for k in KEYS if not isinstance(texts.get(k), str) or not texts[k].strip()]
    if missing:
        raise ValueError(f"connect_texts.yaml misses: {', '.join(missing)}")
    return {k: texts[k] for k in KEYS}


_TEXTS = _load()  # at import: a missing key fails here


def text(key: str) -> str:
    return _TEXTS[key]
