"""The checklist validator (Slice 6a spec S6a-D2, D3; parent §3.2), a pure function.

The items are the research list if confirmed (it replaces the route default's document and statement items), else the
route default, plus the items the student added. Manual and entered items always stay. Each item comes out `ready`,
`missing`, `needs_action` (with reasons) or `manual` (ticked by the student, or not)."""

from dataclasses import dataclass, field, replace
from typing import Literal

from app.os.packs.inputs import ENTERED_PREFIX, PackInputs

State = Literal["ready", "missing", "needs_action", "manual"]
_NOT_YET = {"uploaded": "still being read", "reading": "still being read"}


@dataclass(frozen=True)
class ItemResult:
    key: str
    label: str
    kind: str
    state: State
    ticked: bool = False
    reasons: list[str] = field(default_factory=list)
    source: Literal["research", "default", "student"] = "default"
    document_id: int | None = None
    tickable: bool = False  # the student settles it with a tick (a manual item, or a note no converter can check)


def _effective(inp: PackInputs):
    items = inp.cfg.checklist
    if inp.required_override is None:
        return [(i, "default") for i in items]
    wanted = set(inp.required_override)
    return [(i, "default" if i.kind in ("manual", "entered") else "research") for i in items
            if i.kind in ("manual", "entered") or i.key in wanted]


def checklist(inp: PackInputs, programme_ref: str, unfixable: dict[str, str] | None = None,
              funds=None) -> list[ItemResult]:
    """`unfixable`: item key -> the reason its file could not be made to fit (from the renderer). `funds`: the visa
    file's FundsResult; the config's proof item is then compared with it (Slice 6b S6b-D7)."""
    unfixable = unfixable or {}
    out = []
    for item, source in _effective(inp):
        base = {"key": item.key, "label": item.label, "kind": item.kind, "source": source}
        ticked = item.key in inp.ticked
        if item.kind == "manual":
            out.append(ItemResult(**base, state="manual", ticked=ticked, tickable=True))
        elif item.kind == "entered":
            v = inp.profile.get(ENTERED_PREFIX + item.ref)
            filled = v is not None and v.value not in (None, "")
            out.append(ItemResult(**base, state="ready" if filled else "missing",
                                  reasons=[] if filled else ["fill this in on the details form"]))
        elif item.kind == "statement":
            sha = inp.statements.get(f"{item.ref}:{programme_ref}", inp.statements.get(item.ref))
            out.append(ItemResult(**base, state="ready" if sha else "missing",
                                  reasons=[] if sha else [f"approve your {item.ref.upper()} first"]))
        elif funds is not None and inp.cfg.funds is not None and item.key == inp.cfg.funds.proof_item:
            out.append(_proof(inp, item, base, ticked, unfixable.get(item.key), funds))
        else:
            out.append(_document(inp, item, base, ticked, unfixable.get(item.key)))
    for key, label in inp.added:
        out.append(ItemResult(key=key, label=label, kind="manual", state="manual", ticked=key in inp.ticked,
                              source="student", tickable=True))
    return out


def _document(inp: PackInputs, item, base: dict, ticked: bool, unfixable: str | None) -> ItemResult:
    doc = inp.documents.get(item.ref)
    if doc is None:
        return ItemResult(**base, state="missing", reasons=["upload this document"])
    where = {"document_id": doc.document_id}
    if doc.status in _NOT_YET:
        return ItemResult(**base, **where, state="missing", reasons=[_NOT_YET[doc.status]])
    if doc.status == "failed":
        return ItemResult(**base, **where, state="needs_action", reasons=["upload a clearer copy"])
    if doc.status != "confirmed":
        return ItemResult(**base, **where, state="needs_action", reasons=["check and confirm this document's values"])
    if unfixable:
        return ItemResult(**base, **where, state="needs_action", reasons=[unfixable])
    notes = inp.cfg.format_for(item).notes
    if notes and not ticked:  # what no converter can check: the student confirms it with a tick
        return ItemResult(**base, **where, state="needs_action", reasons=list(notes), tickable=True)
    return ItemResult(**base, **where, state="ready", ticked=ticked, tickable=bool(notes))


def _proof(inp: PackInputs, item, base: dict, ticked: bool, unfixable: str | None, funds) -> ItemResult:
    """The document proving the funds: not needed when other proof covers it all; otherwise its amount must reach
    the requirement, and with no known requirement the student checks it against the official page."""
    from app.os.packs.funds import as_number

    if funds.required == 0:
        return ItemResult(**base, state="ready", reasons=["not needed: your other proof covers the requirement"])
    result = _document(inp, item, base, ticked, unfixable)
    if result.state != "ready":
        return result
    if funds.required is None:
        return replace(result, state="needs_action", reasons=["check the amount against the embassy's page"])
    v = inp.profile.get(f"{item.ref}.{inp.cfg.funds.proof_field}")
    amount = as_number(v.value) if v is not None else None
    if amount is None:
        return replace(result, state="needs_action", reasons=["the amount could not be read; check the document"])
    if amount < funds.required:
        return replace(result, state="needs_action",
                       reasons=[f"the amount is below what you need: {funds.required:g} {funds.currency_label}"])
    return result


def complete(results: list[ItemResult]) -> bool:
    """Every non-manual item is ready and every manual item is ticked: the pack can be approved."""
    return all(r.ticked if r.state == "manual" else r.state == "ready" for r in results)
