"""Discover candidate routes; a search hit alone is never an admission fact."""

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import checked_now, public_https
from urllib.parse import urldefrag, urlsplit


async def discover(context, payload):
    terms = " ".join(str(payload[key]).strip() for key in ("objective", "country", "level")
                     if payload.get(key)).strip()
    queries = (f"{terms} university programme official admissions",
               f"{terms} university course entry requirements tuition")
    candidates = []
    failures = []
    seen = set()
    for query in queries:
        result = await context.tools.invoke("web.search", {"query": query, "limit": 8})
        if not result.get("ok"):
            error = result.get("error") or {}
            failures.append({"reason": error.get("message") or "Search unavailable",
                             "code": error.get("code") or "search_failed"})
            continue
        for hit in result.get("results") or []:
            url = urldefrag(str(hit.get("url") or ""))[0].rstrip("/")
            if not public_https(url) or url in seen:
                continue
            seen.add(url)
            candidates.append({"title": str(hit.get("title") or ""), "url": url,
                               "country": payload.get("country"), "level": payload.get("level"),
                               "why_match": f"Candidate page for {payload['objective']}",
                               "checked_at": checked_now(), "status": "unconfirmed"})
            if len(candidates) >= 8:
                break
        if len(candidates) >= 8:
            break
    for candidate in candidates:
        host = urlsplit(candidate["url"]).hostname
        candidate["related_urls"] = [item["url"] for item in candidates
                                     if item["url"] != candidate["url"]
                                     and urlsplit(item["url"]).hostname == host][:2]
    return {"candidates": candidates, "unconfirmed": failures}


def get_capabilities():
    return [CapabilityContract(
        id="program.discover", version="1.0.0", name="Program discovery",
        description="Find candidate program pages for a stated objective; discovery is not eligibility.",
        input_schema={"type": "object", "properties": {
            "objective": {"type": "string"}, "country": {"type": "string"},
            "level": {"type": "string"}}, "required": ["objective", "country"]},
        output_schema={"type": "object", "properties": {
            "candidates": {"type": "array"}, "unconfirmed": {"type": "array"}},
            "required": ["candidates", "unconfirmed"]},
        handler=discover, owns_task_types=frozenset({"program_discovery"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, vault_scopes=frozenset(),
        permissions=frozenset({"web.read"}), required_tools=frozenset({"web.search"}),
        risk=CapabilityRisk.READ, timeout_seconds=30,
        evidence_expectations={"candidate_urls": "https; unconfirmed until fetched"},
    )]
