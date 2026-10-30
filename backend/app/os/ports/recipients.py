"""The RecipientLookup port (Slice 9b, 9a handoff §7 entry condition 3): a student reference -> their email address.

The outbox stores student references only (in the pilot, the workspace id), never an address. The host knows the
address (workspace -> owner user -> email) and supplies this lookup; the Resend sender calls it at send time, so an
address is never stored in `os_outbox` or `os_events` and never logged.

How each process gets it (invariant 11: no host import here):
- the API process: the host passes `recipient_lookup=` to `mount_os`, which hands it to `ports.configure`;
- the worker process (it never mounts the API): `OS_RECIPIENT_LOOKUP=module.path:callable`, imported at worker start
  like `OS_EXTRA_MODULES`. Unset means nothing is looked up; `OS_EMAIL_SENDER=resend` without it refuses to start.

The lookup returns None (or a blank string) when the student has no address: the row becomes `blocked`. If it raises,
the failure is treated as temporary: the DBOS step retries and the row stays `pending`.
"""

import importlib
from typing import Protocol

from app.os.settings import OsSettings


class RecipientLookup(Protocol):
    def __call__(self, student_ref: str) -> str | None: ...


class RecipientLookupError(ValueError):
    """OS_RECIPIENT_LOOKUP cannot be loaded, or the resend sender has no lookup: the worker must not start."""


_lookup: RecipientLookup | None = None


def configure(lookup: RecipientLookup | None) -> None:
    global _lookup
    _lookup = lookup


def current() -> RecipientLookup | None:
    return _lookup


def load(spec: str) -> RecipientLookup:
    """Imports `module.path:callable`. Any problem is a RecipientLookupError naming the setting (never a value)."""
    module_path, _, name = (spec or "").strip().partition(":")
    if not module_path or not name:
        raise RecipientLookupError("OS_RECIPIENT_LOOKUP must look like 'module.path:callable'")
    try:
        found = getattr(importlib.import_module(module_path), name)
    except (ImportError, AttributeError) as e:
        raise RecipientLookupError(f"OS_RECIPIENT_LOOKUP {spec!r} cannot be imported ({type(e).__name__})") from None
    if not callable(found):
        raise RecipientLookupError(f"OS_RECIPIENT_LOOKUP {spec!r} is not callable")
    return found


def from_settings(settings: OsSettings) -> RecipientLookup | None:
    """The worker's lookup: loaded from OS_RECIPIENT_LOOKUP, or None. Raises when resend would run without one."""
    lookup = load(settings.recipient_lookup) if settings.recipient_lookup else None
    if lookup is None and settings.email_sender == "resend":
        raise RecipientLookupError("OS_EMAIL_SENDER=resend needs OS_RECIPIENT_LOOKUP (module.path:callable, supplied "
                                   "by the host) to find each student's address; the log sender needs none")
    return lookup
