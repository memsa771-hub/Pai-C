"""Source handling for proposed research results."""

import asyncio
from datetime import datetime, timezone
import re
from urllib.parse import urlparse


def checked_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_https(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def data(result: dict) -> dict:
    if not isinstance(result, dict) or not result.get("ok"):
        return {}
    value = result.get("data")
    return value if isinstance(value, dict) else result


def cited_facts(facts: list[dict], content: str, url: str, checked_at: str) -> list[dict]:
    """Only exact page quotations can support extracted claims."""
    accepted = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        quote = str(fact.get("quote") or "").strip()
        if (quote and quote in content and fact.get("field") and fact.get("value") is not None
                and public_https(url)):
            accepted.append({"field": fact["field"], "value": fact["value"],
                             "quote": quote, "source_url": url, "checked_at": checked_at,
                             **{key: fact[key] for key in ("kind", "category", "comparator", "threshold", "unit", "scale", "remediation", "decisive_field", "question_ids")
                                if key in fact}})
    return accepted


async def search_web(query: str, limit: int) -> list[dict]:
    """Web search for background research that belongs to no student (field
    notes, the rules refresh): the same provider and cache as the web.search
    tool, without a workspace. A failure is no results."""
    from app.tools.builtin.web import search
    try:
        found = await search(None, {"query": query, "limit": limit})
    except Exception:  # noqa: BLE001  research works with what it finds
        return []
    return [hit for hit in (found.get("results") or []) if isinstance(hit, dict)] if found.get("ok") else []


async def read_page(url: str, max_chars: int) -> dict | None:
    """SSRF-safe page read with no workspace: {"url", "text"}, or None when the
    page cannot be read. HTML and text go through the /v1/fetch text
    extractor; a PDF (most regulator notices) through the document reader's
    PDF parser, within the same size limit. A PDF cut at that limit is unread,
    never half-read. Script-only pages are not rendered."""
    if not public_https(url):
        return None
    from app.security import network
    from app.routers.fetch import MAX_RESPONSE_BYTES, STATIC_TIMEOUT_SECONDS, USER_AGENT, _extract_text
    from app.inference.usage import record_web_call
    record_web_call("web.fetch")
    try:
        fetched = await network.safe_fetch(url, max_bytes=MAX_RESPONSE_BYTES, timeout=STATIC_TIMEOUT_SECONDS,
                                           headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                                           truncate=True)
    except Exception:  # noqa: BLE001  an unreadable page is a skipped page
        return None
    final = fetched.final_url or url
    if int(fetched.status_code or 0) >= 400 or not public_https(final):
        return None
    kind = fetched.content_type
    if kind == "application/pdf" or fetched.content[:5] == b"%PDF-":
        if fetched.truncated:
            return None
        from app.documents.parsers import parse_pdf
        try:
            # Parsing a 2 MiB PDF is CPU work; keep it off the event loop.
            parsed = await asyncio.to_thread(parse_pdf, fetched.content)
        except Exception:  # noqa: BLE001  a broken or protected PDF is unread
            return None
        text = "\n".join(segment.text for segment in parsed.segments if segment.text).strip()
    elif not kind or any(t in kind for t in ("text/html", "text/plain", "application/xhtml", "application/xml")):
        text = _extract_text(fetched.content.decode("utf-8", errors="replace"), final)["text"].strip()
    else:
        return None
    return {"url": final, "text": text[:max_chars]} if text else None


def same_site(url: str, source: str) -> bool:
    """True when `url` is on the source's own host (or a subdomain of it), so a
    redirect to another site never stands in for the source."""
    def host(value):
        name = (urlparse(str(value or "")).hostname or "").casefold()
        return name[4:] if name.startswith("www.") else name
    a, b = host(url), host(source)
    return bool(a and b) and (a == b or a.endswith("." + b))


def normalized(text) -> str:
    return " ".join(str(text or "").split())


def quote_on_page(quote: str, page: str) -> bool:
    """A quote counts only when it is on the page, ignoring line breaks and
    runs of spaces (PDF and HTML text break lines mid-sentence)."""
    quote = normalized(quote)
    return bool(quote) and quote in normalized(page)


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers(text) -> set[str]:
    """The numbers a text states, without thousands separators ("500,000" is "500000")."""
    found = set()
    for raw in _NUMBER.findall(str(text or "")):
        value = raw.replace(",", "")
        found.add(value[:-2] if value.endswith(".0") else value)
    return found


def real_quote(quote: str, rules: dict) -> bool:
    """A quote is a real passage, not a word: at least min_chars characters and min_words words."""
    quote = normalized(quote)
    return len(quote) >= rules["min_chars"] and len(quote.split()) >= rules["min_words"]


def content_words(text, stopwords) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        if len(word) >= 3 and word not in stopwords:
            words.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return words


def negations(text, words) -> set[str]:
    return set(re.findall(r"[a-z]+", str(text or "").lower())) & set(words)


def quote_supports(text: str, quote: str, rules: dict) -> bool:
    """The quote backs the fact: it is a real passage, every number the fact
    states is in it, the same negation words (rules["negations"]) appear in
    both or in neither, and at least min_support of the fact's content words
    are in the quote. Measured on the fact, so a long quote never penalises a
    true fact, and three invented words ("guaranteed jobs abroad") sink it.
    Known limit: a number the quote uses in another sense ("fee 500,000" read
    as "earn 500,000") still passes; word checks cannot see meaning."""
    if not real_quote(quote, rules) or not numbers(text) <= numbers(quote):
        return False
    if negations(text, rules.get("negations", ())) != negations(quote, rules.get("negations", ())):
        return False
    stop = set(rules.get("stopwords", ()))
    mine, theirs = content_words(text, stop), content_words(quote, stop)
    return bool(mine) and len(mine & theirs) / len(mine) >= rules["min_support"]
