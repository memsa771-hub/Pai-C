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
              student_facts: Callable[[str], dict | None] | None = None,
              choice_enabled: Callable[[], bool] | None = None,
              on_choice_request: Callable[[str], None] | None = None,
              choice_sink: Callable[..., dict | None] | None = None,
              choice_sink_enabled: Callable[[], bool] | None = None,
              document_files: Callable[[str, str], bytes] | None = None,
              documents_enabled: Callable[[], bool] | None = None,
              on_document_deleted: Callable[[str, str], None] | None = None,
              on_fact_proposal: Callable[[str], None] | None = None) -> None:
    """Called by `mount_os`. Slice 9b: also sets the RecipientLookup port (ports.recipients) for this process.
    P1-T4: and the host's StudentFacts adapter (ports.student_facts). P1-T6: and the choice request gate and hook
    (ports.choice_requests); None for both leaves the OS on its own, as before. And the route builder's ChoiceSink
    (ports.choice_sink); None leaves the builder standalone. P1-T7: and the DocumentFiles port (ports.document_files):
    the host's file reader, its gate and its hook for a deleted linked document; None for all three keeps the OS
    storing its own bytes. And the post-commit hook for a fact proposal (ports.fact_proposals); the host's sweep is the
    backup, so None only means the sweep delivers it."""
    from app.os.ports import choice_requests  # late: that module imports this package
    from app.os.ports import choice_sink as choice_sink_port
    from app.os.ports import document_files as document_files_port
    from app.os.ports import fact_proposals
    from app.os.ports import student_facts as student_facts_port  # late: that module imports this package

    global _services
    _services = services
    recipients.configure(recipient_lookup)
    student_facts_port.configure(student_facts)
    choice_requests.configure(choice_enabled, on_choice_request)
    choice_sink_port.configure(choice_sink, choice_sink_enabled)
    document_files_port.configure(document_files, documents_enabled, on_document_deleted)
    fact_proposals.configure(on_fact_proposal)
    from app.os.eligibility import facts as eligibility_facts

    eligibility_facts.configure_types(getattr(services, "document_types", None))  # the types mount_os loaded


def services() -> Services:
    if _services is None:
        raise OsUnavailable("PAI OS is not mounted")
    return _services
