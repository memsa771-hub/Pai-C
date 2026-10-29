# -*- coding: utf-8 -*-
"""The student's chat language, and fixed copy rendered in it (BETA_CONVERSATION_SPEC 2.5).

The classifier reads `{code, script}` from every student message and the
runtime stores it on the workspace (`workspaces.chat_language`), so the
opening, the Writer, the Mirror text and the messages PAI posts on its own all
follow the language of the latest turn. Nothing here names a language: codes
and the onboarding fallback live in policy/languages.json.

Fixed copy (data-file text such as "here are the paths I found") is written in
English. `render_copy` shows it in the chat language: the counselor model
renders it once per copy text and language, and the result is cached on the
workspace (`workspaces.rendered_copy`). English, an unknown language, a paused
model or a failed render all show the English text.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

import regex
from sqlalchemy.orm.attributes import flag_modified

from app.models import Workspace

logger = logging.getLogger(__name__)
_ARABIC = regex.compile(r"\p{Script=Arabic}")
_LATIN = regex.compile(r"\p{Script=Latin}")
# Renders that failed lately (cache key -> monotonic time), per process.
_FAILED: dict[str, float] = {}


def _policy() -> dict:
    from app.pai_c.policy.controller import load_data
    return load_data("languages.json")


def valid_language(value) -> dict | None:
    """`{code, script}` when it is well formed, else None."""
    if not isinstance(value, dict):
        return None
    code, script = value.get("code"), value.get("script")
    if not isinstance(code, str) or not code.isalpha() or not 2 <= len(code) <= 3:
        return None
    if script not in _policy()["scripts"]:
        return None
    return {"code": code.lower(), "script": script}


def is_english(language) -> bool:
    language = valid_language(language)
    return language is None or language["code"] in _policy()["english_codes"]


def chat_language(db, workspace_id: str) -> dict | None:
    workspace = db.get(Workspace, workspace_id)
    return valid_language(workspace.chat_language) if workspace is not None else None


def set_chat_language(db, workspace_id: str, language) -> bool:
    """Store the latest turn's language; the caller commits. True when it changed."""
    language = valid_language(language)
    workspace = db.get(Workspace, workspace_id)
    if language is None or workspace is None or valid_language(workspace.chat_language) == language:
        return False
    workspace.chat_language = language
    return True


def script_of(text: str) -> dict | None:
    """The script most of the letters in `text` are written in, never a
    language: `{code: None, script}`, or None when it has no letters. Used
    before any classifier has read the student (the opening), so the Writer
    matches the student's own words instead of PAI guessing their language."""
    counts = {"arabic": 0, "latin": 0, "other": 0}
    for char in text or "":
        if not char.isalpha():
            continue
        if _ARABIC.match(char):
            counts["arabic"] += 1
        elif _LATIN.match(char):
            counts["latin"] += 1
        else:
            counts["other"] += 1
    if not any(counts.values()):
        return None
    return {"code": None, "script": max(counts, key=counts.get)}


def _cache_key(key: str, english: str, language: dict) -> str:
    digest = hashlib.sha256(english.encode("utf-8")).hexdigest()[:12]
    return f"{key}|{digest}|{language['code']}|{language['script']}"


async def render_copy(db, workspace_id: str, key: str, english: str, language=None) -> str:
    """`english` in the student's chat language, cached per text and language.
    Commits the cache write on `db`."""
    language = valid_language(language) if language is not None else chat_language(db, workspace_id)
    if not english or is_english(language):
        return english
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return english
    cache_key = _cache_key(key, english, language)
    cached = (workspace.rendered_copy or {}).get(cache_key)
    if isinstance(cached, str) and cached.strip():
        return cached
    failed_at = _FAILED.get(cache_key)
    if failed_at is not None and time.monotonic() - failed_at < _policy()["render_retry_seconds"]:
        return english
    from app.inference import usage
    if not usage.role_allowed("counselor"):
        return english
    from app.config import config
    from app.inference.gateway import complete
    from app.pai_c.deep.polish import contains_blocked_script
    from app.pai_c.deep.turn import unfence
    prompt = (Path(__file__).parent / "policy/prompts/copy_render.md").read_text(encoding="utf-8")
    try:
        raw = await complete("counselor", phase="copy_render", system_prompt=prompt,
                             messages=[{"role": "user", "content": json.dumps(
                                 {"language": language, "text": english}, ensure_ascii=False)}],
                             response_format={"type": "json_object"})
        text = json.loads(unfence(raw)).get("text")
        if not isinstance(text, str) or not text.strip() or contains_blocked_script(
                text, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            raise ValueError("invalid rendered copy")
    except Exception as exc:  # noqa: BLE001  the English copy is always a safe answer
        logger.warning("copy_render_failed key=%s error_type=%s", key, type(exc).__name__)
        _FAILED[cache_key] = time.monotonic()
        return english
    workspace = db.get(Workspace, workspace_id)
    # A copy text that changed since (another digest for the same key) is dropped.
    prefix, own = key + "|", cache_key.rsplit("|", 2)[0] + "|"
    kept = {name: value for name, value in (workspace.rendered_copy or {}).items()
            if not name.startswith(prefix) or name.startswith(own)}
    workspace.rendered_copy = {**kept, cache_key: text.strip()}
    flag_modified(workspace, "rendered_copy")
    db.commit()
    return text.strip()
