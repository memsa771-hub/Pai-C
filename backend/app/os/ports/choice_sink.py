"""The ChoiceSink port (P1-T6, R-09). With the `counsellor` module on, the self-serve route builder does not start a
plan of its own: it hands the student's route, intake and places to the host, which writes them through the
Counsellor's decision service. The OS plan then comes from the normal intake of that decision.

This is a synchronous host callback (like StudentFacts): the builder needs the answer to tell the student what
happened. The OS cannot read host flags, so the host answers `None` while its own part is off, and an unconfigured
port answers `None` too. `None` means "not handled": the builder then works standalone, exactly as before.

`request(...)` returns None, or `{"outcome": "written" | "unchanged" | "refused", "decision_version": int | None,
"code": str | None}`. `code` is a reason code (`choose_field_first`, `too_many_places`) on a refusal. Values only
cross as IDs and codes: `intake` is `{"term", "year"}` and `choices` is `[{"programme_ref", "rank"}]`."""

from collections.abc import Callable

_request: Callable[..., dict | None] | None = None


def configure(request: Callable[..., dict | None] | None) -> None:
    global _request
    _request = request


def request(student_ref: str, origin: str, destination: str, level: str, intake: dict, choices: list[dict]) -> dict | None:
    """The host's answer, or None when no host is configured or its part is off. A host that raises is not hidden:
    the builder fails and the student can try again (nothing was written by the OS)."""
    if _request is None:
        return None
    return _request(student_ref, origin, destination, level, intake, choices)
