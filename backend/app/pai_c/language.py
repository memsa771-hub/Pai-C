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
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from app.models import Workspace

logger = logging.getLogger(__name__)


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


def detected_language(text: str) -> dict | None:
    """The language of free text (onboarding answers) by the memory normalizer; None is English."""
    from app.pai_c.memory import detect_language
    return valid_language(_policy()["detected"].get(detect_language(text or "")))


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
        return english
    workspace = db.get(Workspace, workspace_id)
    workspace.rendered_copy = {**(workspace.rendered_copy or {}), cache_key: text.strip()}
    flag_modified(workspace, "rendered_copy")
    db.commit()
    return text.strip()
