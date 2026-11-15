"""Student sentences for the R-39 events (ADR-001 D12). They are data (`texts/event_texts.yaml`) and are shown on plan
screens, cards and notifications only, never as a chat message (R-45). Stored `approved: false` until the owner approves
them: until then they are returned only in rehearsal mode, like the choice texts."""

from functools import cache
from pathlib import Path

import yaml

from app.os.replan.detectors import R39

PATH = Path(__file__).parent / "texts" / "event_texts.yaml"


@cache
def _load(path: Path) -> tuple[bool, dict[str, str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in R39 if not isinstance(raw.get(k), str) or not raw[k].strip()]
    if missing:
        raise ValueError(f"{path.name}: no sentence for {', '.join(missing)}")
    return raw.get("approved") is True, {k: raw[k].strip() for k in R39}


def note(event_type: str, settings, path: Path = PATH) -> str | None:
    """The sentence for an R-39 event, or None while the file is not approved and the OS is not in rehearsal mode."""
    approved, texts = _load(path)
    if not (approved or getattr(settings, "rehearsal", False)):
        return None
    return texts.get(event_type)
