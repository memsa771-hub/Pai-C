"""Data-defined requirements for a reviewable Counselor mirror."""

import json
from pathlib import Path

from app.config import config
from app.pai_c.deep.notebook_schema import CounselorNotebookData, Coverage

_DEFAULT_FILE = Path(__file__).with_name("coverage_requirements.json")


def requirements() -> dict[str, tuple[str, ...]]:
    raw = config.PAI_MIRROR_COVERAGE_REQUIREMENTS_JSON or _DEFAULT_FILE.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid mirror coverage requirements JSON") from exc
    modes = set(CounselorNotebookData.model_fields["depth_mode"].annotation.__args__)
    fields = set(Coverage.model_fields)
    if (not isinstance(parsed, dict) or set(parsed) != modes
            or any(not isinstance(value, list) or not value or
                   any(not isinstance(name, str) or name not in fields for name in value)
                   for value in parsed.values())):
        raise ValueError("invalid mirror coverage requirements")
    return {mode: tuple(value) for mode, value in parsed.items()}


def enforce_mirror_readiness(notebook: CounselorNotebookData) -> CounselorNotebookData:
    required = requirements()[notebook.depth_mode]
    coverage = notebook.coverage.model_dump()
    if notebook.mirror_ready and any(not coverage[key] for key in required):
        return notebook.model_copy(update={"mirror_ready": False})
    return notebook
