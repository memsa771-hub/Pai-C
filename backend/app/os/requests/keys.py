"""The instance keys of the steps the compiler adds for a missing or doubtful fact (P1-T8, D-w5).

`<template>@<kind>:<ref>:<level>` for a request (`provide`, `which_is_right`) and `result_expected@fact:<ref>` for the
step that waits for a result. One module makes them and one parses them, so no other code splits a key by hand."""

from dataclasses import dataclass

PROVIDE = "provide"
WHICH_IS_RIGHT = "which_is_right"
RESULT_EXPECTED = "result_expected"
REQUEST_KINDS = (PROVIDE, WHICH_IS_RIGHT)
TEMPLATES = (*REQUEST_KINDS, RESULT_EXPECTED)  # the template keys of every step the compiler adds for a need
NEED_KINDS = ("fact", "document")
LEVELS = ("stated", "shown", "confirmed")
AWAITING = "awaiting_fact"  # blocked_reason codes the compiler gives a step with an unmet or doubtful need
DOUBT = "which_is_right"
EXPECTED = "result_expected"
BLOCK_CODES = (AWAITING, DOUBT, EXPECTED)


@dataclass(frozen=True)
class RequestKey:
    template: str  # provide | which_is_right | result_expected
    need_kind: str  # fact | document
    ref: str
    level: str | None  # None for result_expected


def make(template: str, need_kind: str, ref: str, level: str | None = None) -> str:
    if template == RESULT_EXPECTED:
        return f"{template}@{need_kind}:{ref}"
    return f"{template}@{need_kind}:{ref}:{level}"


def parse(key: str) -> RequestKey | None:
    """The parts of a generated key, or None for any other key (a playbook step, a fact check, a notice). A key a
    revision has renamed (`#c` cancelled, `#d` done) is not a live request and parses as None."""
    template, sep, rest = key.partition("@")
    if not sep or template not in TEMPLATES or "#" in key:
        return None
    need_kind, sep, rest = rest.partition(":")
    if not sep or need_kind not in NEED_KINDS:
        return None
    if template == RESULT_EXPECTED:
        return RequestKey(template, need_kind, rest, None) if rest else None
    ref, sep, level = rest.rpartition(":")
    if not sep or not ref or level not in LEVELS:
        return None
    return RequestKey(template, need_kind, ref, level)
