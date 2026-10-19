"""Rule-based link choice (spec S2-D5, Spike 1 SP1-D5): the agent never picks what is read next."""

from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

LINK_LIMIT = 5
# Generic web patterns, not country terms: login portals and application forms (robots.txt refuses most),
# accessibility wrappers, and sections that hold no admission facts.
_JUNK = ("qisserver", ".faces", "login", "/sso", "accessibility", "barrier", "doctora", "refugee", "exchange",
         "mailto:", "javascript:", "/news", "/events")


def registrable(host: str) -> str:
    """'www2.example.org' -> 'example.org'. Enough for the university domains in the registry."""
    parts = (host or "").lower().rstrip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


def domain_of(url: str) -> str:
    return registrable(urlsplit(url).hostname or "")


def _wraps_url(url: str) -> bool:
    query = urlsplit(url).query.lower()
    return "http%3a" in query or "http:" in query or "https:" in query or "url=" in query


def rank_links(pages: Iterable, own_domains: Sequence[str], keywords: Sequence[str], seen: set[str],
               limit: int = LINK_LIMIT) -> list[str]:
    """Links on the programme's own domains whose URL or anchor names an application topic, best first.

    Shared hubs are not followed (they held no programme facts in Spike 1); nor are portals or links that
    carry another URL. Ties are broken by URL, so the choice is deterministic.
    """
    own, words = set(own_domains), [k.lower() for k in keywords]
    scores: dict[str, int] = {}
    for page in pages:
        for url, anchor in page.links:
            low = url.lower()
            if url in seen or domain_of(url) not in own or any(j in low for j in _JUNK) or _wraps_url(url):
                continue
            score = sum(w in f"{low} {anchor.lower()}" for w in words)
            if score:
                scores[url] = max(scores.get(url, 0), score)
    return [u for u, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]
