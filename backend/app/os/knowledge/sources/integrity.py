"""Integrity checks on a fetched page (P2 spec §4.2, R-71): spam, link flood, wholesale change, invalid TLS.

Pure functions over text, links and the last clean snapshot; the thresholds and word lists are in `integrity.yaml`.
A finding marks the domain suspect (see `suspect.py`).
"""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from app.os.knowledge.research.text import normalise

CONFIG_FILE = Path(__file__).with_name("integrity.yaml")


@dataclass(frozen=True)
class Finding:
    code: str  # spam | link_flood | wholesale_change | tls_invalid
    detail: str


@dataclass(frozen=True)
class Previous:
    """The last clean snapshot of the same page."""
    text: str
    links_total: int
    links_off_list: int


@cache
def load_config(path: Path = CONFIG_FILE) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("spam", "link_flood", "wholesale_change"):
        if key not in cfg:
            raise ValueError(f"integrity config lacks '{key}'")
    return cfg


def _terms(block: dict) -> list[str]:
    return [str(t).casefold() for words in block.values() for t in words if not isinstance(t, list)] + [
        str(v).casefold() for words in block.values() for t in words if isinstance(t, list) for v in t]


def _stems(block: dict) -> list[tuple[str, ...]]:
    """Each entry is one stem: a word, or a list of the forms of one word (they count once)."""
    out: dict[tuple[str, ...], None] = {}
    for words in block.values():
        for t in words:
            forms = tuple(str(v).casefold() for v in (t if isinstance(t, list) else [t]))
            out[forms] = None
    return list(out)


_TOKEN = re.compile(r"[^\w]+")


def _url_tokens(url: str) -> str:
    parts = urlsplit(url)
    return " " + " ".join(t for t in _TOKEN.split(f"{parts.netloc} {parts.path}".casefold()) if t) + " "


def _word(term: str, hay: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", hay) is not None


def spam_terms(text: str, links: Sequence[tuple[str, str]], cfg: dict) -> list[str]:
    """The distinct spam stems found in the text, the link texts and the link addresses (whole tokens)."""
    hay_text = normalise(" ".join([text, *(a for _, a in links)]))
    hay_urls = [_url_tokens(u) for u, _ in links]
    found = []
    for forms in _stems(cfg["spam"]["terms"]):
        for term in forms:
            joined = " " + term.replace(" ", "") + " "
            spaced = " " + " ".join(normalise(term).split()) + " "
            if _word(term, hay_text) or any(spaced in h or joined in h for h in hay_urls):
                found.append(forms[0])
                break
    return found


def off_list_links(links: Sequence[tuple[str, str]], on_list: Callable[[str], bool]) -> int:
    return sum(1 for u, _ in links if not on_list(u))


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = normalise(text).split()
    if len(words) < 3:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def similarity(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def check_page(text: str, links: Sequence[tuple[str, str]], on_list: Callable[[str], bool],
               previous: Previous | None, cfg: dict | None = None) -> list[Finding]:
    cfg = cfg or load_config()
    out: list[Finding] = []
    hits = spam_terms(text, links, cfg)
    if len(hits) >= cfg["spam"]["min_distinct_terms"]:
        out.append(Finding("spam", ", ".join(hits)))

    fl = cfg["link_flood"]
    off, total = off_list_links(links, on_list), len(links)
    share = off / total if total else 0.0
    before = (previous.links_off_list / previous.links_total) if previous and previous.links_total else 0.0
    if previous is not None and off >= fl["min_off_list_links"] and share >= fl["min_share"] and share - before >= fl["min_increase"]:
        out.append(Finding("link_flood", f"{off} of {total} links off the lists (before: {before:.2f})"))

    wc = cfg["wholesale_change"]
    if previous and len(previous.text.split()) >= wc["min_words_before"]:
        sim = similarity(previous.text, text)
        if sim < wc["max_similarity"]:
            old, new = normalise(previous.text), normalise(text)
            markers = _terms(wc["explained_by"])
            explained = any(re.search(rf"(?<!\w){re.escape(m)}(?!\w)", new)
                            and not re.search(rf"(?<!\w){re.escape(m)}(?!\w)", old) for m in markers)
            if not explained:
                out.append(Finding("wholesale_change", f"similarity {sim:.2f}"))
    return out


def is_tls_failure(exc: BaseException) -> bool:
    """A certificate verification failure (verify failed, hostname mismatch, expired) anywhere in the exception chain.
    Other SSL errors (protocol, EOF, version) are transient, like any network error."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False
