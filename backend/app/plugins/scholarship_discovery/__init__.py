"""Scholarship leads, always marked unconfirmed until their official source is read."""

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import checked_now, public_https


async def discover(context, payload):
    query = " ".join(str(payload.get(key) or "") for key in ("country", "level", "field"))
    result = await context.tools.invoke("web.search", {
        "query": query + " university scholarship official international students", "limit": 6})
    leads = []
    if result.get("ok"):
        for hit in result.get("results") or []:
            if public_https(hit.get("url")):
                leads.append({"title": str(hit.get("title") or ""),
                              "source_url": hit["url"], "checked_at": checked_now(),
                              "status": "unconfirmed"})
    return {"scholarships": [], "unconfirmed": leads}


def get_capabilities():
    return [CapabilityContract(
        id="scholarship.discover", version="1.0.0", name="Scholarship discovery",
        description="Find scholarship leads without inventing awards or eligibility.",
        input_schema={"type": "object", "properties": {
            "country": {"type": "string"}, "level": {"type": "string"},
            "field": {"type": "string"}}, "required": ["country"]},
        output_schema={"type": "object", "properties": {
            "scholarships": {"type": "array"}, "unconfirmed": {"type": "array"}},
            "required": ["scholarships", "unconfirmed"]},
        handler=discover, owns_task_types=frozenset({"scholarship_discovery"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, vault_scopes=frozenset(),
        permissions=frozenset({"web.read"}), required_tools=frozenset({"web.search"}),
        risk=CapabilityRisk.READ, timeout_seconds=30,
        evidence_expectations={"scholarship_urls": "search leads remain unconfirmed"},
    )]
