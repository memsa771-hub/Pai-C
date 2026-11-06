"""The one upload entry point, Counsellor side (P1-T7, R-01, row 6.7, D-y2, D-y3, D-y5).

A file is stored once, in the Counsellor file store. When the student names a document type, the file is also made an
OS document that reads it from there (the OS keeps no bytes of its own, D-y1). This module holds the two things the
routes share: `register_typed` and `options`. The sentences live in `upload_texts.yaml` (approved by the owner); a
missing key stops startup. Only the bridge talks to PAI OS."""

import logging
from pathlib import Path

import yaml

from app import pai_os_bridge as bridge

log = logging.getLogger("app.pai_c.connect.uploads")

TEXTS_PATH = Path(__file__).with_name("upload_texts.yaml")
KEYS = ("type_label", "type_none", "registered", "consent_needed", "duplicate", "unknown_type", "not_readable")
# The refusal codes that have a sentence. `terms_not_set` and `not_on` have none (no approved copy): note is None.
REFUSAL_TEXT = {"consent_needed": "consent_needed", "duplicate": "duplicate", "unknown_type": "unknown_type",
                "not_readable": "not_readable"}


def _load() -> dict[str, str]:
    raw = yaml.safe_load(TEXTS_PATH.read_text(encoding="utf-8")) or {}
    if raw.get("approved") is not True:
        raise ValueError("upload_texts.yaml is not approved by the owner")
    texts = raw.get("texts") or {}
    missing = [k for k in KEYS if not isinstance(texts.get(k), str) or not texts[k].strip()]
    if missing:
        raise ValueError(f"upload_texts.yaml misses: {', '.join(missing)}")
    return {k: texts[k].strip() for k in KEYS}


_TEXTS = _load()  # at import: a missing key fails here


def text(key: str) -> str:
    return _TEXTS[key]


def register_typed(db, workspace_id: str, file_id: str, data: bytes, filename: str, doc_type: str) -> dict:
    """Makes the stored file `file_id` an OS document of `doc_type`. Never raises: the file is already stored and an
    upload does not fail over derived state. Returns `{"id", "status", "note"}` when registered, else
    `{"refused": code, "note": sentence | None}`. (`db` is the caller's session; the OS has its own database.)"""
    try:
        got = bridge.register_os_document(workspace_id, doc_type, file_id, filename, data)
    except Exception as exc:  # noqa: BLE001  (class name only: no file content, no student data)
        log.error("registering a typed upload failed: %s", type(exc).__name__)
        return {"refused": "failed", "note": None}
    code = got.get("refused")
    if code is not None:
        key = REFUSAL_TEXT.get(code)
        return {"refused": code, "note": text(key) if key else None}
    return {"id": got["id"], "status": got["status"], "note": text("registered")}


def options() -> dict:
    """What the upload screens need (D-y5). Exactly `{"one_upload": false}` while the part is off."""
    if not bridge.documents_enabled():
        return {"one_upload": False}
    return {"one_upload": True, "doc_types": bridge.document_types(),
            "text": {k: text(k) for k in KEYS}}
