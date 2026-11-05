"""The StudentFacts port, event side (P1-T4, P1-D15): the host hands PAI OS a Vault event, a notice that facts of a
student changed (keys only, never values). It is only stored here (one insert); the replan that reads it comes later.
Sending the same version again is harmless."""

import json
from typing import Literal

from pydantic import ValidationError

from app.os import ports
from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.store import VaultEventStore
from app.os.contracts.vault_event import VaultEventV1


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
