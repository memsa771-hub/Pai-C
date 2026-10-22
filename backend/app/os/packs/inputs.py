"""What a pack is built from (Slice 6a spec §2): the student's documents, approved statements and profile values, the
programme's facts, the playbook's constants and citations, and the student's ticks and added items. The pure rules
(checklist, data sheet, instructions) read only this, so they can be tested without a database."""

from dataclasses import dataclass, field
from typing import Any

from app.os.packs.config import PackConfig

ENTERED_PREFIX = "entered."  # profile key of a value the student typed: "entered.<data-sheet field key>"


@dataclass(frozen=True)
class DocState:
    status: str  # the os_documents status: uploaded, reading, read, needs_student, confirmed, failed
    document_id: int
    sha256: str | None


@dataclass(frozen=True)
class ProfileValue:
    value: Any
    source: str  # "document" or "entered"
    document_id: int | None


@dataclass(frozen=True)
class PackInputs:
    cfg: PackConfig
    documents: dict[str, DocState]  # by document type: the student's live document of that type
    statements: dict[str, str | None]  # "sop", "cv", and "sop:<programme>" when needed -> approved SHA-256 or None
    profile: dict[str, ProfileValue]
    facts: dict[str, Any]  # fact name -> knowledge Fact (value, url, status) for this programme and intake
    constants: dict[str, Any]  # playbook constants (value, citations, estimate)
    citations: dict[str, str]  # playbook citation source id -> URL
    ticked: set[str] = field(default_factory=set)
    added: list[tuple[str, str]] = field(default_factory=list)  # (item key, label) the student added
    required_override: list[str] | None = None  # the confirmed required_documents fact, if any


def show(value: Any) -> str:
    """A fact or constant value as one short line (no country-specific formatting)."""
    if isinstance(value, dict) and "date" in value:
        return str(value["date"])
    if isinstance(value, list):
        return ", ".join(show(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dict):
        return ", ".join(f"{k.replace('_', ' ')} {show(v)}" for k, v in value.items() if v is not None)
    return str(value)
