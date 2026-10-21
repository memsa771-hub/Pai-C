"""The one language everything outside the chat is written in.

The Counselor talks in the student's language. Whatever lands in the
workspace (Vault values, Background notes, paths and their checks) is stored
in the workspace language from `workspace_language.json`, so the product
reads as one professional application whatever the student types. Shared by
memory and PAI-C, so it lives outside both.
"""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def workspace_language() -> dict:
    data = json.loads(Path(__file__).with_name("workspace_language.json").read_text(encoding="utf-8"))
    return {"language": data["language"], "style": data["style"]}


def workspace_language_block() -> str:
    """The input block prompts refer to as <workspace_language>."""
    return "<workspace_language>" + json.dumps(workspace_language(), ensure_ascii=False) + "</workspace_language>"
