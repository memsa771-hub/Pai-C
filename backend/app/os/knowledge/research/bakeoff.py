"""The ScanText bake-off (P2-D13): each engine reads the same fictional scans; the score is whether the quotes still
match the page by the trust rule (`quote_on_page`, after normalisation), then text similarity, then time.

The rule from the spec: the winner must pass the quote-match on the fixtures. An engine that is not installed is
reported as `not run`, never scored. No engine is paid here; a paid vision adapter would be added only within the
owner's cost cap.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.os.knowledge.research.scan import ScanFailed, ScanText, scan_document
from app.os.knowledge.research.text import normalise
from app.os.knowledge.research.trust import quote_on_page


@dataclass(frozen=True)
class Case:
    name: str
    data: bytes
    content_type: str
    language: str  # our code, as on facts
    quotes: tuple[str, ...]  # what a fact would quote from this document


@dataclass(frozen=True)
class Score:
    engine: str
    case: str
    ran: bool
    quotes_found: int = 0
    quotes_total: int = 0
    similarity: float = 0.0
    seconds: float = 0.0
    error: str | None = None


def run_bakeoff(adapters: Sequence[ScanText], cases: Sequence[Case], *, max_pages: int = 5) -> list[Score]:
    out: list[Score] = []
    for adapter in adapters:
        for case in cases:
            if not adapter.available():
                out.append(Score(adapter.name, case.name, ran=False, quotes_total=len(case.quotes),
                                 error="not installed"))
                continue
            start = time.perf_counter()
            try:
                got = scan_document(adapter, case.data, case.content_type, max_pages=max_pages, languages=(case.language,))
            except ScanFailed as e:
                out.append(Score(adapter.name, case.name, ran=True, quotes_total=len(case.quotes),
                                 seconds=time.perf_counter() - start, error=str(e)))
                continue
            took = time.perf_counter() - start
            page = normalise(got.text)
            found = sum(1 for q in case.quotes if quote_on_page(q, page))
            expected = normalise("\n".join(case.quotes))
            out.append(Score(adapter.name, case.name, ran=True, quotes_found=found, quotes_total=len(case.quotes),
                             similarity=SequenceMatcher(None, expected, page).ratio(), seconds=took))
    return out


def summarise(scores: Sequence[Score]) -> dict[str, dict]:
    """Per engine: cases, cases run, quote pass rate (of all quotes), mean similarity and time, failures."""
    by: dict[str, list[Score]] = {}
    for s in scores:
        by.setdefault(s.engine, []).append(s)
    out = {}
    for engine, rows in by.items():
        ran = [r for r in rows if r.ran]
        total = sum(r.quotes_total for r in rows)
        out[engine] = {
            "cases": len(rows), "ran": len(ran),
            "quote_pass_rate": (sum(r.quotes_found for r in ran) / total) if ran and total else None,
            "mean_similarity": (sum(r.similarity for r in ran) / len(ran)) if ran else None,
            "mean_seconds": (sum(r.seconds for r in ran) / len(ran)) if ran else None,
            "failures": sum(1 for r in ran if r.error),
        }
    return out


def winner(summary: dict[str, dict]) -> str | None:
    """The engine that ran every case, failed none and matched every quote; the best similarity breaks a tie.
    None when no engine qualifies (including when none was installed)."""
    ok = {e: s for e, s in summary.items()
          if s["ran"] == s["cases"] and s["failures"] == 0 and s["quote_pass_rate"] == 1.0}
    return max(ok, key=lambda e: ok[e]["mean_similarity"]) if ok else None
