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


QUOTE_WINDOW = 400  # characters: a label and its value, or a cut passage, must sit this close together


def quote_on_page(quote: str, page_norm: str) -> bool:
    """The quote is on the page as one passage, or as pieces (split at line breaks or '...') that appear
    in order within QUOTE_WINDOW characters of the first piece: table rows and cut passages, never
    words gathered from across the page."""
    whole = normalise(quote)
    if not whole:
        return False
    if whole in page_norm:
        return True
    pieces = [p for p in (normalise(s) for s in re.split(r"\.\.\.|…|\n", quote)) if p]
    if len(pieces) < 2:
        return False
    start = page_norm.find(pieces[0])
    while start != -1:
        pos, ok = start + len(pieces[0]), True
        for piece in pieces[1:]:
            pos = page_norm.find(piece, pos)
            if pos == -1 or pos + len(piece) - start > QUOTE_WINDOW:
                ok = False
                break
            pos += len(piece)
        if ok:
            return True
        start = page_norm.find(pieces[0], start + 1)
    return False


def _check(fact: Found, pages: dict[str, str], domains: tuple[str, ...]) -> list[str]:
    problems = []
    text = pages.get(fact.url)
    if text is None:
        problems.append("url_not_read")
    elif not quote_on_page(fact.quote, text):
        problems.append("quote_not_on_page")
    if not is_official(fact.url, domains):
        problems.append("not_official")
    return problems


def valid_count(fact_by_reading: dict[str, Found | None], pages: dict[str, str], domains: tuple[str, ...]) -> int:
    return sum(1 for f in fact_by_reading.values() if f is not None and not _check(f, pages, domains))


def judge(field_name: str, a: Found | None, b: Found | None, pages: dict[str, str],
          domains: tuple[str, ...], min_cycle: int, c: Found | None = None) -> Verdict:
    """Confirmed needs at least two valid readings and every valid reading to agree: reading C can
    stand in for a missing or rejected reading, never outvote one that disagrees."""
    readings = {"A": a, "B": b, "C": c}
    if all(f is None for f in readings.values()):
        return Verdict("not_found")
    checked = {name: (f, _check(f, pages, domains)) for name, f in readings.items() if f is not None}
    good = {n: f for n, (f, problems) in checked.items() if not problems}
    reasons = [f"{n}:{p}" for n, (_, problems) in checked.items() for p in problems]
    if not good:
        return Verdict("unconfirmed", reasons=reasons or ["no_valid_reading"])
    best = next(iter(good.values()))
    v = Verdict("unconfirmed", _value(best), best.quote, best.url, reasons=reasons)
    if len(good) < 2:
        v.reasons.append("single_reading")
        return v
    if len({canon(field_name, f.value) for f in good.values()}) > 1:
        v.reasons.append("readings_disagree")
        v.conflict_note = " ".join(f"{n}={_value(f)!r}" for n, f in good.items())
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


def page_texts(pages: list[Page]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for p in pages:
        if p.ok:
            texts[p.url] = normalise(p.text)
            if p.final_url:
                texts.setdefault(p.final_url, texts[p.url])
    return texts


def needs_third_reading(a: Reading | None, b: Reading | None, pages: list[Page], domains: tuple[str, ...]) -> bool:
    """True when some field has exactly one valid reading from A and B."""
    texts = page_texts(pages)
    return any(valid_count({"A": getattr(a, f, None), "B": getattr(b, f, None)}, texts, domains) == 1
               for f in FIELDS)


def judge_programme(a: Reading | None, b: Reading | None, pages: list[Page],
                    domains: tuple[str, ...], min_cycle: int, c: Reading | None = None) -> dict[str, Verdict]:
    texts = page_texts(pages)
    return {f: judge(f, getattr(a, f, None), getattr(b, f, None), texts, domains, min_cycle, getattr(c, f, None))
            for f in FIELDS}
