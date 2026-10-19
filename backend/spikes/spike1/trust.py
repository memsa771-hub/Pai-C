"""Deterministic trust checks (SP1-D7): official source, quote on the page, two readings agree, cycle.

No AI. A fact is `confirmed` only when every check passes; otherwise it is `unconfirmed` with the
reasons, or `not_found` when neither reading reports it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from spikes.spike1.fields import CYCLE_BOUND, FIELDS, Found, Reading, canon
from spikes.spike1.pages import Page, is_official, normalise

_YEAR = re.compile(r"\b(20\d\d)\b")


@dataclass
class Verdict:
    status: str  # confirmed | unconfirmed | not_found
    value: Any = None
    quote: str | None = None
    url: str | None = None
    cycle_year: int | None = None
    reasons: list[str] = field(default_factory=list)
    conflict_note: str | None = None


def cycle_year(fact: Found, page_text_norm: str) -> int | None:
    """The newest year named by the fact's cycle or quote that also appears on its page."""
    years = [int(y) for y in _YEAR.findall(f"{fact.cycle or ''} {fact.quote}") if y in page_text_norm]
    return max(years) if years else None


def _check(fact: Found, pages: dict[str, str], domains: tuple[str, ...]) -> list[str]:
    problems = []
    text = pages.get(fact.url)
    if text is None:
        problems.append("url_not_read")
    elif not fact.quote.strip() or normalise(fact.quote) not in text:
        problems.append("quote_not_on_page")
    if not is_official(fact.url, domains):
        problems.append("not_official")
    return problems


def judge(field_name: str, a: Found | None, b: Found | None, pages: dict[str, str],
          domains: tuple[str, ...], min_cycle: int) -> Verdict:
    if a is None and b is None:
        return Verdict("not_found")
    checked = {name: (f, _check(f, pages, domains)) for name, f in (("A", a), ("B", b)) if f is not None}
    good = {n: f for n, (f, problems) in checked.items() if not problems}
    reasons = [f"{n}:{p}" for n, (_, problems) in checked.items() for p in problems]
    if not good:
        return Verdict("unconfirmed", reasons=reasons or ["no_valid_reading"])
    best = good.get("A") or good["B"]
    v = Verdict("unconfirmed", _value(best), best.quote, best.url, reasons=reasons)
    if len(good) < 2:
        v.reasons.append("single_reading")
        return v
    if canon(field_name, good["A"].value) != canon(field_name, good["B"].value):
        v.reasons.append("readings_disagree")
        v.conflict_note = f"A={_value(good['A'])!r} B={_value(good['B'])!r}"
        return v
    if field_name in CYCLE_BOUND:
        years = [y for f in good.values() if (y := cycle_year(f, pages[f.url])) is not None]
        v.cycle_year = max(years) if years else None
        if v.cycle_year is None:
            v.reasons.append("cycle_unknown")
            return v
        if v.cycle_year < min_cycle:
            v.reasons.append(f"cycle_old:{v.cycle_year}")
            return v
    v.status = "confirmed"
    return v


def _value(f: Found) -> Any:
    return f.value.model_dump() if hasattr(f.value, "model_dump") else f.value


def judge_programme(a: Reading | None, b: Reading | None, pages: list[Page],
                    domains: tuple[str, ...], min_cycle: int) -> dict[str, Verdict]:
    texts: dict[str, str] = {}
    for p in pages:
        if p.ok:
            texts[p.url] = normalise(p.text)
            if p.final_url:
                texts.setdefault(p.final_url, texts[p.url])
    return {f: judge(f, getattr(a, f, None), getattr(b, f, None), texts, domains, min_cycle) for f in FIELDS}
