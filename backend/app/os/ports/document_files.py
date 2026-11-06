"""The DocumentFiles port (P1-T7, P1-D2, D-y1, D-y6, D-y7).

When the Counsellor is connected, a student's file is stored once, in the Counsellor file store. The OS document
that reads it carries the Counsellor file ID as `file_ref` and has no bytes of its own. This port is how the OS
reaches those bytes and how the host tells the OS about files.

Host side (all optional; an unconfigured port is the OS exactly as it was, with its own `os_document_files` table):
- `read(student_ref, file_ref) -> bytes`: the bytes of the student's file. Any failure is `KeyError`. The worker
  loads it from `OS_DOCUMENT_FILES=module.path:callable`, like `OS_STUDENT_FACTS`; the API gets it from `mount_os`.
- `enabled() -> bool`: whether the host part is on (the OS cannot read host flags). False when unconfigured or when
  the callable raises.
- `on_deleted(student_ref, file_ref)`: called after the OS has deleted a linked document, so the host can purge the
  file (D-y7). Errors are swallowed by the caller.

OS side, called by the host (through the mounted services; no host import, invariant 11):
- `register(...)` makes an OS document for a file the host has stored, and starts its reading.
- `forget(...)` deletes the OS document linked to a file the host has deleted."""

import importlib
import logging
from collections.abc import Callable

from app.os import ports
from app.os.settings import OsSettings

log = logging.getLogger("app.os.ports.document_files")

Read = Callable[[str, str], bytes]


class DocumentFilesSourceError(ValueError):
    """OS_DOCUMENT_FILES cannot be loaded: the worker must not start."""


class Refused(Exception):
    """`register` did not make a document. `code` is one of not_on, unknown_type, consent_needed, terms_not_set,
    not_readable, duplicate."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_read: Read | None = None
_enabled: Callable[[], bool] | None = None
_on_deleted: Callable[[str, str], None] | None = None


def configure(read: Read | None = None, enabled: Callable[[], bool] | None = None,
              on_deleted: Callable[[str, str], None] | None = None) -> None:
    global _read, _enabled, _on_deleted
    _read, _enabled, _on_deleted = read, enabled, on_deleted


def current() -> Read | None:
    return _read


def load(spec: str) -> Read:
    """Imports `module.path:callable`. Any problem is a DocumentFilesSourceError naming the setting (never a value)."""
    module_path, _, name = (spec or "").strip().partition(":")
    if not module_path or not name:
        raise DocumentFilesSourceError("OS_DOCUMENT_FILES must look like 'module.path:callable'")
    try:
        found = getattr(importlib.import_module(module_path), name)
    except (ImportError, AttributeError) as e:
        raise DocumentFilesSourceError(f"OS_DOCUMENT_FILES cannot be imported ({type(e).__name__})") from None
    if not callable(found):
        raise DocumentFilesSourceError("OS_DOCUMENT_FILES is not callable")
    return found


def from_settings(settings: OsSettings) -> Read | None:
    """The worker's host reader: loaded from OS_DOCUMENT_FILES, or None."""
    return load(settings.document_files) if settings.document_files else None


def enabled() -> bool:
    if _enabled is None:
        return False
    try:
        return bool(_enabled())
    except Exception as e:  # a failing gate means off, never a failing upload
        log.error("document files gate failed (%s)", type(e).__name__)
        return False


def read(student_ref: str, file_ref: str) -> bytes:
    """The bytes of a linked file. `KeyError` when no reader is configured or the host cannot give them."""
    if _read is None:
        raise KeyError(file_ref)
    return _read(student_ref, file_ref)


def on_deleted(student_ref: str, file_ref: str) -> None:
    """Tells the host a linked document is deleted (no-op when unconfigured). Raises what the host raises."""
    if _on_deleted is not None:
        _on_deleted(student_ref, file_ref)


def register(student_ref: str, doc_type: str, file_ref: str, filename: str, data: bytes) -> dict:
    """Makes an OS document for a file the host stored, and enqueues its reading. Returns `{"id", "status"}`.
    Refuses with `Refused(code)`, checking in this order: the port is on, the type is known, the pilot terms are
    agreed, the file is readable, the file is not already registered."""
    from app.os.consent import gate  # late: keep this module light for the confirm code that imports it
    from app.os.documents.intake import UploadError, check_upload
    from app.os.documents.run import enqueue_document
    from app.os.documents.store import DocumentStore, DuplicateDocument

    if not enabled():
        raise Refused("not_on")
    svc = ports.services()
    t = svc.document_types.get(doc_type)
    if t is None:
        raise Refused("unknown_type")
    code = gate.upload_refusal(svc, student_ref)
    if code is not None:
        raise Refused(code)
    name = (filename or "document")[:255]
    try:
        kind = check_upload(name, data)
    except UploadError:
        raise Refused("not_readable") from None
    tenant = svc.settings.tenant_id
    store = DocumentStore(svc.engine, tenant)
    try:
        doc_id = store.create_ref(student_ref, doc_type, t.version, name,
                                  "application/pdf" if kind == "pdf" else f"image/{kind}", data, file_ref)
    except DuplicateDocument:
        raise Refused("duplicate") from None
    doc = store.get(doc_id)
    enqueue_document(svc.dbos_client(), tenant, doc)  # if this is lost, the daily documents_retry sends it
    return {"id": doc_id, "status": doc.status}


def forget(student_ref: str, file_ref: str) -> bool:
    """Deletes the student's OS document linked to `file_ref` (fields, profile values, workflows and pack files, as a
    delete by the student does), without telling the host back. False when the student has none."""
    from app.os.documents.confirm import delete_document
    from app.os.documents.store import DocumentStore

    svc = ports.services()
    store = DocumentStore(svc.engine, svc.settings.tenant_id)
    doc = store.find_by_file_ref(student_ref, file_ref)
    if doc is None:
        return False
    delete_document(svc.engine, svc.settings.tenant_id, svc.document_types, svc.name_variants, doc,
                    client=svc.dbos_client(), notify_host=False)
    return True
