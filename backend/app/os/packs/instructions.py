"""The programme's instructions and fees (Slice 6a spec S6a-D6, D11): the route template for the programme's
confirmed application route, filled from its facts and the playbook's constants, each step with its source. A fact
that is not confirmed is shown as "not confirmed yet", never guessed."""

import re
from dataclasses import dataclass, field

from app.os.packs.inputs import PackInputs, show

NOT_CONFIRMED = "not confirmed yet"
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


@dataclass(frozen=True)
class InstructionStep:
    n: int
    text: str
    source_url: str | None
    unconfirmed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeeRow:
    label: str
    value: str | None
    status: str  # confirmed, unconfirmed, stale, estimate or missing
    source_url: str | None


def _confirmed(inp: PackInputs, name: str):
    f = inp.facts.get(name)
    return f if f is not None and f.status == "confirmed" else None


def _url(inp: PackInputs, source: str) -> str | None:
    kind, _, name = source.partition(":")
    if kind == "fact":
        f = inp.facts.get(name)
        return f.url if f is not None and f.url else None
    if kind == "citation":
        return inp.citations.get(name)
    c = inp.constants.get(name)
    return str(c.citations[0].url) if c is not None and c.citations else None


def _not_confirmed_text(kind: str, name: str | None, university: str | None) -> str:
    """The one step shown while the programme's application route is not confirmed, naming the programme and its
    university when they are known (Slice 9 Task 11, `walk:S1:visa_how_to_apply_programme_text`)."""
    programme = f"{name} at {university}" if name and university else name or university or "this programme"
    ask = university or "the university"
    if kind == "visa":
        return (f"Your visa steps depend on how you apply to {programme}, and that is {NOT_CONFIRMED}: check the "
                f"programme's page, or ask {ask}.")
    return f"How to apply to {programme} is {NOT_CONFIRMED}: check the programme's page, or ask {ask}."


def instructions(inp: PackInputs, programme_ref: str, name: str | None = None,
                 university: str | None = None) -> tuple[str | None, list[InstructionStep]]:
    """(the application route used, its steps). Without a confirmed route there is one step saying so, naming the
    programme (`name`) and its university when given."""
    route = _confirmed(inp, "application_route")
    if route is None or route.value not in inp.cfg.instructions:
        text = _not_confirmed_text(inp.kind, name, university)
        return None, [InstructionStep(1, text, _url(inp, "fact:application_route"), ["application_route"])]
    steps = []
    for n, step in enumerate(inp.cfg.instructions[route.value], 1):
        missing: list[str] = []

        def fill(m: re.Match) -> str:
            name = m.group(1)
            if name in inp.constants:
                return show(inp.constants[name].value)
            f = _confirmed(inp, name)
            if f is None:
                missing.append(name)
                return NOT_CONFIRMED
            return show(f.value)

        steps.append(InstructionStep(n, _PLACEHOLDER.sub(fill, step.text), _url(inp, step.source), missing))
    return route.value, steps


def fees(inp: PackInputs) -> list[FeeRow]:
    rows = []
    for fee in inp.cfg.fees:
        kind, _, name = fee.source.partition(":")
        if kind == "constant":
            c = inp.constants.get(name)
            status = "missing" if c is None else "estimate" if c.estimate else "confirmed"
            rows.append(FeeRow(fee.label, None if c is None else show(c.value), status, _url(inp, fee.source)))
        else:
            f = inp.facts.get(name)
            rows.append(FeeRow(fee.label, None if f is None else show(f.value),
                               "missing" if f is None else f.status, _url(inp, fee.source)))
    return rows
