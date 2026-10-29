"""Source handling for proposed research results."""

from datetime import datetime, timezone
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
    """Static, SSRF-safe page read with no workspace (the first tier of
    /v1/fetch): {"url", "text"}, or None when the page cannot be read as text
    (a PDF, a script-only page, an unsafe address)."""
    if not public_https(url):
        return None
    from app.routers.fetch import _extract_text, _static_fetch
    try:
        fetched = await _static_fetch(url)
    except Exception:  # noqa: BLE001  an unreadable page is a skipped page
        return None
    final = fetched.get("final_url") or url
    text = _extract_text(fetched["html"], final)["text"].strip()
    if not text or not public_https(final) or int(fetched.get("status_code") or 0) >= 400:
        return None
    return {"url": final, "text": text[:max_chars]}
