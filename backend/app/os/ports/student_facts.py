"""The StudentFacts port (P1-T4).

Event side (P1-D15): the host hands PAI OS a Vault event, a notice that facts of a student changed (keys only, never
values). It is only stored here (one insert); the replan that reads it comes later. Sending the same version again is
harmless.

Read side: `get(student_ref)` returns the student's `StudentFactsV1`. With the `counsellor` module on and a host
adapter configured, the host's adapter answers; it returns None while the host's own part is off, and then (like when
the module is off or no adapter is set) the standalone adapter answers, from `os_profile_values`.

How each process gets the host adapter (invariant 11: no host import here):
- the API process: the host passes `student_facts=` to `mount_os`, which hands it to `ports.configure`;
- the worker process: `OS_STUDENT_FACTS=module.path:callable`, imported at worker start like `OS_RECIPIENT_LOOKUP`.
Unset means no host adapter: the standalone one always answers."""

import importlib
import json
from collections.abc import Callable
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import Engine

from app.os import ports
from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.store import VaultEventStore
from app.os.adapters.standalone.student_facts import build as standalone_build
from app.os.contracts.student_facts import StudentFactsV1
from app.os.contracts.vault_event import VaultEventV1
from app.os.settings import OsSettings

StudentFactsSource = Callable[[str], dict | None]


class StudentFactsSourceError(ValueError):
    """OS_STUDENT_FACTS cannot be loaded: the worker must not start."""


_source: StudentFactsSource | None = None


def configure(source: StudentFactsSource | None) -> None:
    global _source
    _source = source


def current() -> StudentFactsSource | None:
    return _source


def load(spec: str) -> StudentFactsSource:
    """Imports `module.path:callable`. Any problem is a StudentFactsSourceError naming the setting (never a value)."""
    module_path, _, name = (spec or "").strip().partition(":")
    if not module_path or not name:
        raise StudentFactsSourceError("OS_STUDENT_FACTS must look like 'module.path:callable'")
    try:
        found = getattr(importlib.import_module(module_path), name)
    except (ImportError, AttributeError) as e:
        raise StudentFactsSourceError(f"OS_STUDENT_FACTS {spec!r} cannot be imported ({type(e).__name__})") from None
    if not callable(found):
        raise StudentFactsSourceError(f"OS_STUDENT_FACTS {spec!r} is not callable")
    return found


def from_settings(settings: OsSettings) -> StudentFactsSource | None:
    """The worker's host adapter: loaded from OS_STUDENT_FACTS, or None."""
    return load(settings.student_facts) if settings.student_facts else None


def counsellor_active(engine: Engine, tenant_id: str) -> bool:
    """True when a host adapter is set and the `counsellor` module is on."""
    return _source is not None and manifest.is_enabled(engine, tenant_id)


def get(student_ref: str, *, engine: Engine | None = None, tenant_id: str | None = None) -> StudentFactsV1:
    """The student's facts. `engine` and `tenant_id` default to the mounted services (callers inside the OS that hold
    their own engine pass them). A host adapter that raises is not hidden: the caller retries or fails."""
    if engine is None or tenant_id is None:
        svc = ports.services()
        engine, tenant_id = svc.engine, svc.settings.tenant_id
    if counsellor_active(engine, tenant_id):
        raw = _source(student_ref)
        if raw is not None:
            return StudentFactsV1.model_validate(raw)
    from app.os.eligibility.facts import default_types  # late: the eligibility code imports this port

    return standalone_build(engine, tenant_id, student_ref, default_types())


def record_event(event: dict) -> Literal["stored", "duplicate", "module_off"]:
    """Validates the event against VaultEventV1 (ValueError when it is not) and stores it, even while the
    `counsellor` module is off (it waits until switched on, like a decision)."""
    try:
        checked = VaultEventV1.model_validate(event)
    except ValidationError as exc:
        raise ValueError("invalid vault event") from exc
    svc = ports.services()
    tenant = svc.settings.tenant_id
    stored = VaultEventStore(svc.engine, tenant).add(json.loads(checked.model_dump_json(by_alias=True)))
    if not manifest.is_enabled(svc.engine, tenant):
        return "module_off"
    return "stored" if stored else "duplicate"


def latest_vault_version(student_ref: str) -> int | None:
    """The highest Vault version stored for the student (None when none is)."""
    svc = ports.services()
    return VaultEventStore(svc.engine, svc.settings.tenant_id).latest_version(student_ref)
