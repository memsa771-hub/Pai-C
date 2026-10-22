"""The rule-based invented-facts check (Slice 5 spec S5-D5). No AI.

Every number, date and name in a draft must appear in the student's answers or confirmed profile values. A claim
that does not is "unsupported": the Writer gets it back to remove (or the Critic turns it into a question), and the
student sees it highlighted. Formats are normalised first, so "3.40" and "3.4", or "15 July 2023" and "2023-07-15",
are the same fact. Generic English only: no country, institution or test is named here (invariant 12).
"""

import re
from dataclasses import dataclass
from typing import Literal

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], 1)}
MONTHS |= {m[:3]: i for m, i in list(MONTHS.items())} | {"sept": 9}
_MONTH = r"(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"

_DATES = [  # most precise first; each match is masked before the next pattern runs
    ("dmy", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\s+(\d{{4}})\b", re.I)),
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("my", re.compile(rf"\b({_MONTH})\s+(\d{{4}})\b", re.I)),
    ("ym", re.compile(r"\b(\d{4})-(\d{2})\b")),
    ("y", re.compile(r"\b((?:19|20)\d{2})\b")),
]
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")
_WORD = re.compile(r"[A-Za-z][A-Za-z&'\-]*|[^\sA-Za-z]")
_CONNECTORS = {"of", "and", "for", "the", "in", "at", "de", "&"}
# Capitalised only because they start a sentence or are everyday words: never a name on their own.
_STARTERS = {"a", "an", "the", "my", "our", "his", "her", "their", "its", "this", "that", "these", "those", "in", "at",
             "on", "during", "after", "before", "as", "when", "while", "with", "from", "for", "to", "by", "since",
             "also", "and", "but", "so", "then", "there", "here", "it", "we", "you", "they", "he", "she"}
ALLOWED_NAMES = {"i", "cv", "sop", "dear", "sir", "madam", "yours", "sincerely"} | set(MONTHS)
_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


@dataclass(frozen=True)
class Claim:
    kind: Literal["number", "date", "name"]
    text: str
    norm: str
    start: int = 0


def _month(s: str) -> int:
    return MONTHS[s.lower().rstrip(".")]


def _date_norm(kind: str, m: re.Match) -> str:
    if kind == "dmy":
        return f"{int(m[3]):04d}-{_month(m[2]):02d}-{int(m[1]):02d}"
    if kind == "iso":
        return f"{m[1]}-{m[2]}-{m[3]}"
    if kind == "my":
        return f"{int(m[2]):04d}-{_month(m[1]):02d}"
    if kind == "ym":
        return f"{m[1]}-{m[2]}"
    return m[1]


def normalise(kind: str, text: str) -> str:
    if kind == "number":
        v = float(text.replace(",", ""))
        return str(int(v)) if v.is_integer() else f"{v:g}"
    if kind == "date":
        for k, pat in _DATES:
            m = pat.fullmatch(text.strip())
            if m:
                return _date_norm(k, m)
        return text.strip()
    return " ".join(re.sub(r"[^\w\s&]|_", " ", text.casefold()).split())  # "ielts_trf.overall" holds "ielts"


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _names(text: str) -> list[Claim]:
    out, run = [], []

    def flush():
        while run and run[0][0].lower() in _STARTERS | _CONNECTORS:
            run.pop(0)
        while run and run[-1][0].lower() in _CONNECTORS:
            run.pop()
        caps = [w for w, _ in run if w[0].isupper()]
        if len(caps) >= 2 or (len(caps) == 1 and len(run) == 1 and caps[0].isupper() and len(caps[0]) >= 2):
            if not (len(run) == 1 and run[0][0].lower() in ALLOWED_NAMES):
                start, end = run[0][1], run[-1][1] + len(run[-1][0])
                phrase = text[start:end]
                out.append(Claim("name", phrase, normalise("name", phrase), start))
        run.clear()

    for m in _WORD.finditer(text):
        w = m.group()
        word = w[0].isalpha()
        low = w.lower()
        if word and w[0].isupper() and low not in _DAYS and not (low in ALLOWED_NAMES and len(w) <= 4 and w != w.upper()):
            if low == "i":
                flush()
                continue
            run.append((w, m.start()))
        elif word and run and low in _CONNECTORS:
            run.append((w, m.start()))
        else:
            flush()
    flush()
    return out


def claims(text: str) -> list[Claim]:
    """Every number, date and name in `text`, in order of appearance."""
    found: list[Claim] = []
    masked = text
    for kind, pat in _DATES:
        for m in pat.finditer(masked):
            found.append(Claim("date", text[m.start():m.end()], _date_norm(kind, m), m.start()))
            masked = _mask(masked, m.start(), m.end())
    for m in _NUMBER.finditer(masked):
        found.append(Claim("number", m.group(), normalise("number", m.group()), m.start()))
    found += _names(masked)
    return sorted(found, key=lambda c: c.start)


def unsupported(draft: str, sources: list[str]) -> list[Claim]:
    """The claims in `draft` that no source supports. A date is supported by the same date or a more precise one
    (a year by any date in that year); a name by the same words anywhere in a source."""
    numbers, dates, texts = set(), set(), []
    for s in sources:
        for c in claims(s):
            (numbers if c.kind == "number" else dates if c.kind == "date" else set()).add(c.norm)
        texts.append(f" {normalise('name', s)} ")
    out = []
    for c in claims(draft):
        if c.kind == "number":
            ok = c.norm in numbers
        elif c.kind == "date":
            ok = any(d == c.norm or d.startswith(c.norm + "-") for d in dates)
        else:
            ok = any(f" {c.norm} " in t for t in texts)
        if not ok:
            out.append(c)
    return out
