"""Trust rules and evidence validators (Slice 2 spec §4.4, S2-D6, S2-D9). No AI.

A reading's fact is valid only if every check passes: official source, quote on the page, not a link label,
the value is in the quote, a one-item list is stated as complete, and the rule's scope covers the programme.
A field is `confirmed` only if at least two readings are valid, all valid readings agree, and (for cycle-bound
fields) the page's cycle is the intake's. Anything else is `unconfirmed` with its reasons, or `not_found`
when no reading reports the field. Every reading's value, quote, URL, scope quote and failures are kept as
the fact's evidence.

Python knows only the generic field types; aliases, month names and phrases come from the route's profile.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from app.os.knowledge.research.links import domain_of
from app.os.knowledge.research.text import normalise

QUOTE_WINDOW = 400  # a label and its value, or the pieces of a cut passage, sit this close together (Spike 1)
SCOPE_WINDOW = 2000  # a scope quote must be this close to the quote it scopes
SCORE_WINDOW = 150  # a page "lists scores" when a score's name has a number this close after it
_YEAR = re.compile(r"\b(20\d\d)\b")
_NUMBER = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*")


@dataclass
class Verdict:
    status: str  # confirmed | unconfirmed | not_found
    value: Any = None
    quote: str | None = None
    url: str | None = None
    cycle_year: int | None = None
    reasons: list[str] = field(default_factory=list)
    conflict_note: str | None = None
    evidence: list[dict] = field(default_factory=list)


# --- text helpers ------------------------------------------------------------------------------------------


def _has(phrase: str, text_norm: str) -> bool:
    """`phrase` appears in the normalised text as whole words (a trailing footnote digit is allowed)."""
    p = normalise(phrase)
    return bool(p) and re.search(rf"(?<!\w){re.escape(p)}(?![^\W\d_])", text_norm) is not None


def _any(phrases: Sequence[str], text_norm: str) -> bool:
    return any(_has(p, text_norm) for p in phrases)


def _numbers(text: str) -> set[float]:
    """Every number the text may state, reading 1.234,56 and 1,234.56 both ways where they are ambiguous."""
    found: set[float] = set()
    for tok in _NUMBER.findall(text):
        if "." in tok and "," in tok:
            dec = max(tok.rfind("."), tok.rfind(","))
            found.add(float(re.sub(r"[.,]", "", tok[:dec]) + "." + tok[dec + 1:]))
            continue
        sep = "." if "." in tok else "," if "," in tok else None
        if sep is None:
            found.add(float(tok))
            continue
        parts = tok.split(sep)
        if len(parts) > 2:  # 1.234.567: thousands separators
            found.add(float("".join(parts)))
            continue
        found.add(float(f"{parts[0]}.{parts[1]}"))
        if len(parts[1]) == 3:
            found.add(float(parts[0] + parts[1]))
    return found


def _number_in(value: float, text: str) -> bool:
    return any(abs(n - float(value)) < 1e-6 for n in _numbers(text))


def _dump(value: Any) -> Any:
    return value.model_dump() if hasattr(value, "model_dump") else value


# --- 2. quote on the page ----------------------------------------------------------------------------------


def _quote_span(quote: str, page_norm: str) -> tuple[int, int] | None:
    """Where the quote is on the page: as one passage, or as pieces (split at line breaks or '...') in order
    within QUOTE_WINDOW characters of the first piece. Never words gathered from across the page."""
    whole = normalise(quote or "")
    if not whole:
        return None
    at = page_norm.find(whole)
    if at != -1:
        return at, at + len(whole)
    pieces = [p for p in (normalise(s) for s in re.split(r"\.\.\.|…|\n", quote)) if p]
    if len(pieces) < 2:
        return None
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
            return start, pos
        start = page_norm.find(pieces[0], start + 1)
    return None


def quote_on_page(quote: str, page_norm: str) -> bool:
    return _quote_span(quote, page_norm) is not None


# --- 3. not a link label -----------------------------------------------------------------------------------


def is_link_label(quote: str, page) -> bool:
    """The quote is an anchor text on the page, or a list of anchors under a lead-in line ending in ':'
    (a menu). Spike 1 lesson 5, D4."""
    anchors = {normalise(a) for _, a in page.links if a and a.strip()}
    if normalise(quote) in anchors:
        return True
    lines = [line for line in (normalise(s) for s in quote.splitlines()) if line]
    content = [line for line in lines if not line.endswith(":")]
    return len(lines) > 1 and bool(content) and all(line in anchors for line in content)


# --- 4. the value is in the quote --------------------------------------------------------------------------


def _month_day_in(value: str, q: str, profile) -> bool:
    month, day = (int(x) for x in value.split("-"))
    numeric = (re.search(rf"(?<!\d)0?{day}\s?[./]\s?0?{month}(?!\d)", q)
               or re.search(rf"\d{{4}}-0?{month}-0?{day}(?!\d)", q)
               or re.search(rf"(?<!\d)0?{month}/0?{day}/", q))
    if numeric:
        return True
    named = _any(profile.month_names[month], q)
    return named and re.search(rf"(?<!\d)0?{day}(?!\d)", q) is not None


def value_in_quote(spec, value, quote: str, profile) -> bool:
    """The quote states the value (Spike 1 lesson 1, D5), by the field's generic type."""
    q, v = normalise(quote or ""), _dump(value)
    none = profile.none_phrases.get(spec.name, [])
    if spec.type == "month_day":
        return _month_day_in(v, q, profile)
    if spec.type == "amount":
        return _number_in(v, q) or (float(v) == 0 and _any(none, q))
    if spec.type == "enum":
        return _any(spec.values.get(v, []), q)
    if spec.type == "level":
        return _any(none, q) if v["level"] == "none" else _has(v["level"], q)
    if spec.type in ("grade", "numbers"):
        given = [x for x in (v.get(p) for p in spec.parts) if x is not None]
        return bool(given) and all(_number_in(x, q) for x in given)
    if spec.type == "level_scores":
        scores = {s: v[s] for s in spec.scores if v.get(s) is not None}
        flags = [f for f in spec.flags if v.get(f) is True]  # granting something must be stated; withholding not
        if not scores and v.get("cefr") is None:
            return False
        if not scores and not _has(v["cefr"], q):  # a level alone must be stated
            return False
        for s, x in scores.items():
            if not _number_in(x, q) or (spec.values.get(s) and not _any(spec.values[s], q)):
                return False
        return all(spec.values.get(f) and _any(spec.values[f], q) for f in flags)
    items = v["any_of"] if spec.type == "name_set" else v
    if not items:
        return spec.type == "name_set" and _any(none, q)
    return all(spec.values.get(i) and _any(spec.values[i], q) for i in items)


# --- 5. complete lists -------------------------------------------------------------------------------------


def list_complete(spec, value, quote: str, profile) -> bool:
    """A one-item intake list or test list counts only if the quote says it is the only one (lesson 3, D1)."""
    if spec.type not in ("season_set", "name_set"):
        return True
    v = _dump(value)
    items = v["any_of"] if spec.type == "name_set" else v
    return len(items) != 1 or _any(profile.exclusive_phrases, normalise(quote or ""))


# --- 6. scope ----------------------------------------------------------------------------------------------


def _names(programme) -> list[str]:
    return [n for n in (programme.name, *programme.aliases) if n and n.strip()]


def _and(text: str) -> str:
    return re.sub(r"\s*&\s*", " and ", text)


def _url_form(text: str) -> str:
    return normalise(re.sub(r"[-_/.+?=&%#]+", " ", unquote(text)))


def _own_folder(url: str) -> str | None:
    """'https://h/a/b/page.html' -> 'https://h/a/b/'. None when the folder is less than two levels deep
    ('/' or '/en/'), which is the whole site or one language of it, not a programme."""
    parts = urlsplit(url)
    folder = parts.path.rsplit("/", 1)[0] + "/"
    if len([s for s in folder.split("/") if s]) < 2:
        return None
    return f"{parts.scheme}://{parts.netloc.lower()}{folder}"


def _under_own_page(urls: list[str], programme) -> bool:
    """The page is one of the programme's own start pages (no other programme starts there), or sits in one's
    folder (its FAQ, its how-to-apply page)."""
    own = [u for u in getattr(programme, "own_pages", ()) if u]
    folders = [f for f in (_own_folder(u) for u in own) if f]
    for u in urls:
        low = f"{urlsplit(u).scheme}://{urlsplit(u).netloc.lower()}{urlsplit(u).path}"
        if u in own or any(low.startswith(f) for f in folders):
            return True
    return False


def _page_is_specific(page, programme) -> bool:
    """The page is one of the programme's own pages, or its title (its first line) or URL names the programme or
    an alias ('&' reads as 'and'; in a URL, words may be joined by hyphens or run together)."""
    title = _and(normalise(page.text.split("\n", 1)[0])) if page.text else ""
    urls = [u for u in (page.url, page.final_url) if u]
    if _under_own_page(urls, programme):
        return True
    url_words = " ".join(_url_form(u) for u in urls)
    url_compact = re.sub(r"[^a-z0-9]", "", " ".join(unquote(u).lower() for u in urls))
    for name in _names(programme):
        compact = re.sub(r"[^a-z0-9]", "", _and(name.lower()))
        if (_has(_and(name), title) or _has(_url_form(name), url_words)
                or (len(compact) >= 6 and compact in url_compact)):
            return True
    return False


def scope_ok(page, programme, quote: str, scope_quote: str | None, profile) -> bool:
    """A rule on a general page counts only with a scope quote that is on the page, within SCOPE_WINDOW
    characters of the quote, and names the programme or says the rule is for every programme (lesson 2, D3)."""
    if _page_is_specific(page, programme):
        return True
    if not scope_quote:
        return False
    text = normalise(page.text)
    q, s = _quote_span(quote, text), _quote_span(scope_quote, text)
    if q is None or s is None or max(0, max(q[0], s[0]) - min(q[1], s[1])) > SCOPE_WINDOW:
        return False
    s_norm = normalise(scope_quote)
    return _any(_names(programme), s_norm) or _any(profile.scope_all_phrases, s_norm)


# --- judge -------------------------------------------------------------------------------------------------


def _lists_scores(page_norm: str, spec) -> bool:
    """The page names a test score: a score's name followed closely by a plausible number (not a year)."""
    for s in spec.scores:
        for alias in spec.values.get(s, []):
            for m in re.finditer(rf"(?<!\w){re.escape(normalise(alias))}", page_norm):
                after = page_norm[m.end(): m.end() + SCORE_WINDOW]
                if any(n < 1000 for n in _numbers(after)):
                    return True
    return False


def cycle_year(fact, page_norm: str) -> int | None:
    """The newest year named by the fact's cycle or quote that also appears on its page."""
    years = [int(y) for y in _YEAR.findall(f"{fact.cycle or ''} {fact.quote}") if y in page_norm]
    return max(years) if years else None


def canon(spec, value) -> Any:
    """A hashable form: two readings agree when their canons are equal."""
    v = _dump(value)
    if spec.type == "amount":
        return round(float(v), 2)
    if spec.type == "level":
        return v["level"]
    if spec.type == "name_set":
        return tuple(sorted(set(v["any_of"])))
    if spec.type == "season_set":
        return tuple(sorted(set(v)))
    if isinstance(v, dict):
        return tuple(sorted((k, round(x, 2) if isinstance(x, float) else x) for k, x in v.items() if x is not None))
    return v


def _check(spec, fact, texts: Mapping[str, str], by_url: Mapping, programme, profile, official: set[str],
           run_lists_scores: bool) -> list[str]:
    problems = []
    if domain_of(fact.url) not in official:
        problems.append("not_official")
    page = by_url.get(fact.url)
    if page is None:
        return problems + ["url_not_read"]
    if not quote_on_page(fact.quote, texts[fact.url]):
        problems.append("quote_not_on_page")
    if is_link_label(fact.quote, page):
        problems.append("link_label")
    if not value_in_quote(spec, fact.value, fact.quote, profile):
        problems.append("value_not_in_quote")
    if not list_complete(spec, fact.value, fact.quote, profile):
        problems.append("list_not_complete")
    if not scope_ok(page, programme, fact.quote, fact.scope_quote, profile):
        problems.append("scope_unclear")
    if spec.type == "level_scores" and run_lists_scores:
        v = _dump(fact.value)
        if all(v.get(s) is None for s in spec.scores):  # a level alone, while a page in the run lists scores
            problems.append("scores_on_other_page")
    return problems


def judge(spec, readings: Mapping[str, Any], pages: Sequence, programme, profile, min_cycle: int) -> Verdict:
    """One field's verdict from readings A, B (and C). C can stand in for a missing or rejected reading,
    never outvote one that disagrees. `min_cycle` is the intake year a cycle-bound fact must be for (S2-D9)."""
    present = {n: f for n, f in readings.items() if f is not None}
    if not present:
        return Verdict("not_found")
    by_url, texts = {}, {}
    for p in pages:
        if p.ok:
            for u in (p.url, p.final_url):
                if u and u not in by_url:
                    by_url[u], texts[u] = p, normalise(p.text)
    official = set(programme.official_domains) | set(profile.official_sources)
    run_lists_scores = spec.type == "level_scores" and any(_lists_scores(t, spec) for t in set(texts.values()))
    checked = {n: _check(spec, f, texts, by_url, programme, profile, official, run_lists_scores)
               for n, f in present.items()}
    evidence = [{"reading": n, "value": _dump(f.value), "quote": f.quote, "url": f.url, "cycle": f.cycle,
                 "scope_quote": f.scope_quote, "reasons": checked[n]} for n, f in present.items()]
    reasons = [f"{n}:{p}" for n, problems in checked.items() for p in problems]
    good = {n: f for n, f in present.items() if not checked[n]}
    if not good:
        return Verdict("unconfirmed", reasons=reasons or ["no_valid_reading"], evidence=evidence)
    best = next(iter(good.values()))
    v = Verdict("unconfirmed", _dump(best.value), best.quote, best.url, reasons=reasons, evidence=evidence)
    if len(good) < 2:
        v.reasons.append("single_reading")
        return v
    if len({canon(spec, f.value) for f in good.values()}) > 1:
        v.reasons.append("readings_disagree")
        v.conflict_note = " ".join(f"{n}={_dump(f.value)!r}" for n, f in good.items())
        return v
    if spec.cycle_bound:
        years = [y for f in good.values() if (y := cycle_year(f, texts[f.url])) is not None]
        v.cycle_year = max(years) if years else None
        if v.cycle_year is None:
            v.reasons.append("cycle_unknown")
            return v
        if v.cycle_year < min_cycle:
            v.reasons.append(f"cycle_old:{v.cycle_year}")
            shown = next((f.cycle for f in good.values() if f.cycle), None) or str(v.cycle_year)
            v.conflict_note = f"page shows {shown}"
            return v
    v.status = "confirmed"
    return v
