"""Load the versioned Counselor prompts without embedding prompt text in code."""

from functools import lru_cache
from pathlib import Path


_PROMPT_DIR = Path(__file__).with_name("prompts")
_NAMES = frozenset({"voice", "voice_guided", "planner", "mirror", "sensitive_check", "language_retry", "handoff", "session_summary", "wellbeing", "myth_check", "path_analyzer"})


@lru_cache(maxsize=len(_NAMES))
def load_prompt(name: str) -> str:
    if name not in _NAMES:
        raise ValueError(f"Unknown Counselor prompt: {name}")
    folder = {"planner": "planner", "voice": "voice", "voice_guided": "voice"}.get(name)
    directory = _PROMPT_DIR.parent.parent / folder / "prompts" if folder else _PROMPT_DIR
    return (directory / f"{name}.md").read_text(encoding="utf-8")
