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
                             **{key: fact[key] for key in ("kind", "category", "comparator", "threshold", "unit", "scale", "remediation")
                                if key in fact}})
    return accepted
