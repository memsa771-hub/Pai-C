"""Discover candidate routes; a search hit alone is never an admission fact."""

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import checked_now, public_https


async def discover(context, payload):
    query = " ".join(str(payload[key]).strip() for key in ("objective", "country", "level")
                     if payload.get(key)) + " university official program admissions"
    result = await context.tools.invoke("web.search", {"query": query, "limit": 8})
    if not result.get("ok"):
        return {"candidates": [], "unconfirmed": [{"reason": "Search unavailable"}]}
    candidates = []
    for hit in result.get("results") or []:
        url = hit.get("url")
        if public_https(url):
            candidates.append({"title": str(hit.get("title") or ""), "url": url,
                               "country": payload.get("country"), "level": payload.get("level"),
                               "checked_at": checked_now(), "status": "unconfirmed"})
    return {"candidates": candidates, "unconfirmed": []}


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
