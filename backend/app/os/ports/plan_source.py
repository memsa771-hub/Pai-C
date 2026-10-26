"""The PlanSource port (Slice 8 spec §2.2, S8-D6): the host hands PAI OS a Counsellor decision export. It is only
stored here (one insert, no planning in the request); the worker's `counsellor.intake` job plans it. Submitting the
same decision again is harmless (S8-D9)."""

import hashlib
import json
from typing import Literal

from app.os import ports
from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.store import IntakeStore, SweepStore

_NEEDED = ("decision_id", "journey_id", "student_ref", "chosen_at")


def export_sha256(export: dict) -> str:
    canonical = json.dumps(export, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def submit_counsellor_decision(export: dict) -> Literal["stored", "duplicate", "module_off"]:
    """Stores the export as pending, even while the module is off (it waits until switched on). The rest of the
    export is checked by the worker, which refuses an invalid one with a reason; only an export missing what the
    intake row is keyed on cannot be stored (ValueError)."""
    missing = [k for k in _NEEDED if not export.get(k)]
    if missing:
        raise ValueError(f"export lacks {', '.join(missing)}")
    svc = ports.services()
    tenant = svc.settings.tenant_id
    stored = IntakeStore(svc.engine, tenant).add(export, export_sha256(export))
    if not manifest.is_enabled(svc.engine, tenant):
        return "module_off"
    return "stored" if stored else "duplicate"


def sweep_mark() -> dict | None:
    """The glue's sweep position (the last chosen_at and decision ID it submitted)."""
    svc = ports.services()
    return SweepStore(svc.engine, svc.settings.tenant_id).mark()


def set_sweep_mark(mark: dict) -> None:
    svc = ports.services()
    SweepStore(svc.engine, svc.settings.tenant_id).set_mark(mark)
