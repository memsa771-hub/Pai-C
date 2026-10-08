"""Load the versioned Counselor prompts without embedding prompt text in code."""

from functools import lru_cache
from pathlib import Path


_PROMPT_DIR = Path(__file__).with_name("prompts")
_NAMES = frozenset({"counselor", "analyst", "mirror", "roadmap_builder", "sensitive_check", "language_retry"})


@lru_cache(maxsize=len(_NAMES))
def load_prompt(name: str) -> str:
    if name not in _NAMES:
        raise ValueError(f"Unknown Counselor prompt: {name}")
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
