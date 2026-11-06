"""The student sentences for an escalation pause (escalation_texts.yaml, R-11). The texts live in the YAML file, never
in code. While `approved` is false they are returned only in rehearsal (`config.CONNECT_CONSENT_DRAFT`), else `None`.
Import fails when a reason has no sentence."""

from pathlib import Path

import yaml

from app.config import config

TEXTS_PATH = Path(__file__).with_name("escalation_texts.yaml")
REASONS = ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other")


def _load() -> dict:
    raw = yaml.safe_load(TEXTS_PATH.read_text(encoding="utf-8")) or {}
    reasons = raw.get("reasons") or {}
    missing = [r for r in REASONS if not isinstance(reasons.get(r), str) or not reasons[r].strip()]
    if missing or not isinstance(raw.get("action"), str) or not raw["action"].strip():
        raise ValueError(f"{TEXTS_PATH.name}: no text for {', '.join(missing) or 'action'}")
    return raw


_RAW = _load()


def _usable() -> bool:
    return bool(_RAW.get("approved")) or bool(config.CONNECT_CONSENT_DRAFT)


def text(reason: str) -> str | None:
    """The sentence for a reason code; None for an unknown code or while the texts are not approved."""
    if reason not in REASONS or not _usable():
        return None
    return _RAW["reasons"][reason].strip()


def action() -> str | None:
    """The banner button's label; None while the texts are not approved."""
    return _RAW["action"].strip() if _usable() else None
