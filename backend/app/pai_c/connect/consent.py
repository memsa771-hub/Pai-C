"""The consent texts (consent_texts.yaml) and the gate that keeps unapproved texts away from real students (R-10).

The texts live in the YAML file, never in code. While `approved` is false, nothing may show or send them unless
`config.CONNECT_CONSENT_DRAFT` is on (rehearsal).
"""

from pathlib import Path

import yaml

from app.config import config

TEXTS_PATH = Path(__file__).with_name("consent_texts.yaml")


class ConsentTextNotApproved(Exception):
    pass


def texts() -> dict:
    """The consent texts as written in the YAML file."""
    return yaml.safe_load(TEXTS_PATH.read_text(encoding="utf-8")) or {}


def current_version() -> str:
    return str(texts()["version"])


def ensure_usable() -> None:
    """Raises `ConsentTextNotApproved` unless the texts are approved or the draft flag is on."""
    if not texts().get("approved") and not config.CONNECT_CONSENT_DRAFT:
        raise ConsentTextNotApproved("The consent texts are not approved yet")
