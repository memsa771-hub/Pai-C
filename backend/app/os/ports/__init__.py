"""The ports (Slice 8 spec §2.2, parent §3): the only PAI OS code the host calls for the Counsellor connection. They are
configured when the OS is mounted and need no host import (invariant 11)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from app.os.ports import recipients
from app.os.ports.recipients import RecipientLookup

if TYPE_CHECKING:  # the replan code and the worker import the ports: they must not pull in the API
    from app.os.api.services import Services


class OsUnavailable(RuntimeError):
    """PAI OS is not mounted (OS_ENABLED off or no database): the host carries on without it."""


_services: Services | None = None


def configure(services: Services | None, recipient_lookup: RecipientLookup | None = None,
              student_facts: Callable[[str], dict | None] | None = None) -> None:
    """Called by `mount_os`. Slice 9b: also sets the RecipientLookup port (ports.recipients) for this process.
    P1-T4: and the host's StudentFacts adapter (ports.student_facts)."""
    from app.os.ports import student_facts as student_facts_port  # late: that module imports this package

    global _services
    _services = services
    recipients.configure(recipient_lookup)
    student_facts_port.configure(student_facts)
    from app.os.eligibility import facts as eligibility_facts

    eligibility_facts.configure_types(getattr(services, "document_types", None))  # the types mount_os loaded


def services() -> Services:
    if _services is None:
        raise OsUnavailable("PAI OS is not mounted")
    return _services
