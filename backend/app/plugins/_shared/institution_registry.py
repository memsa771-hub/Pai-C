"""Resolve a research page against a separate institutional identity registry.

Search results and student supplied URLs cannot assert their own officialness.
ROR supplies a provider backed website claim; an unmatched institution remains
unconfirmed. This is deliberately optional when the registry is unavailable.
"""

import json
import httpx

from app.infrastructure.cache import get_bytes, set_bytes
from app.plugins._shared.verification import _host, official_url


ROR_SEARCH_URL = "https://api.ror.org/v2/organizations"


def registry_identity(page_url: str, response: dict) -> dict | None:
    """Accept only one active record whose website actually owns the page host."""
    matches = []
    for item in response.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "active":
            continue
        websites = [link.get("value") for link in item.get("links") or []
                    if isinstance(link, dict) and link.get("type") == "website"]
        domains = {_host(value) for value in websites}
        domains.discard(None)
        matching = {domain for domain in domains if official_url(page_url, {domain})}
        if not matching or not item.get("id"):
            continue
        primary = next((name.get("value") for name in item.get("names") or []
                        if isinstance(name, dict) and "ror_display" in (name.get("types") or [])), None)
        name = primary or next((name.get("value") for name in item.get("names") or []
                                if isinstance(name, dict) and name.get("value")), None)
        country = next((location.get("geonames_details", {}).get("country_code")
                        for location in item.get("locations") or []
                        if isinstance(location, dict) and
                        (location.get("geonames_details") or {}).get("country_code")), None)
        if name and country:
            matching_website = next(value for value in websites
                                    if _host(value) in matching)
            matches.append({"name": name, "country_code": country,
                            "provider_id": item["id"], "website_url": matching_website,
                            "domains": sorted(matching)})
    return matches[0] if len(matches) == 1 else None


async def resolve_institution(page_url: str) -> dict | None:
    host = _host(page_url)
    if not host:
        return None
    cache_key = f"ror:website:v1:{host}"
    cached = get_bytes(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except (TypeError, ValueError):
            pass
    # The endpoint is fixed. The hostname is only a query value, never a fetch
    # destination, so an untrusted search result cannot redirect this request.
    try:
        labels = host.split(".")
        candidates = [".".join(labels[index:]) for index in range(min(3, len(labels) - 1))]
        identity = None
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            for candidate in candidates:
                result = await client.get(ROR_SEARCH_URL,
                                          params={"query.advanced": f'links.value:"{candidate}"'},
                                          headers={"Accept": "application/json"})
                result.raise_for_status()
                identity = registry_identity(page_url, result.json())
                if identity:
                    break
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    set_bytes(cache_key, json.dumps(identity).encode(), 24 * 60 * 60)
    return identity
