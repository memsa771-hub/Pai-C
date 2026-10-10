"""Official scholarship leads with exact cited facts; never inferred awards."""

import json

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import checked_now, cited_facts, data, public_https
from app.plugins._shared.verification import official_url


EXTRACTION_PROMPT = (
    "Extract only scholarship facts explicitly printed on this official page. "
    "Return JSON with a facts array. Each fact is {field,value,quote}. "
    "Allowed fields: scholarship.name, scholarship.eligibility, "
    "scholarship.amount, scholarship.deadline, scholarship.application_route. "
    "Use ISO date only when explicit; do not guess currency, amount, year, "
    "student eligibility or an award. Quote an exact contiguous page excerpt. "
    "Use an empty array when the page is unclear."
)


async def _extract(content: str, url: str) -> list[dict]:
    from app.config import config
    from app.inference.gateway import complete as chat_completion, resolve_model

    raw = await chat_completion(role="research_extract",
        api_key=config.PAI_API_KEY, model=resolve_model("research_extract"),
        system_prompt=EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": json.dumps({
            "source_url": url, "page": content[:16000]}, ensure_ascii=False)}],
        max_tokens=900, base_url=config.PAI_BASE_URL or None)
    parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    allowed = {"scholarship.name", "scholarship.eligibility", "scholarship.amount",
               "scholarship.deadline", "scholarship.application_route"}
    facts = cited_facts(parsed.get("facts") or [], content, url, checked_now())
    return [fact for fact in facts if fact["field"] in allowed]


async def discover(context, payload):
    query = " ".join(str(payload.get(key) or "") for key in ("country", "level", "field"))
    result = await context.tools.invoke("web.search", {
        "query": query + " university scholarship official international students", "limit": 6})
    if not result.get("ok"):
        error = result.get("error") or {}
        return {"scholarships": [], "unconfirmed": [{
            "reason": error.get("message") or "Search unavailable",
            "code": error.get("code") or "search_failed"}]}
    scholarships = []
    unconfirmed = []
    for hit in (result.get("results") or [])[:3]:
        url = str(hit.get("url") or "")
        if not public_https(url):
            continue
        registry = data(await context.tools.invoke("web.institution_registry", {"url": url}))
        identity = registry.get("identity")
        if not identity or not official_url(url, set(identity.get("domains") or [])):
            unconfirmed.append({"source_url": url, "reason": "Scholarship page is not on a trusted official domain"})
            continue
        page = data(await context.tools.invoke("web.fetch", {"url": url, "max_chars": 18000}))
        actual_url = str(page.get("url") or url)
        content = str(page.get("content") or "")
        if not content or not official_url(actual_url, set(identity.get("domains") or [])):
            unconfirmed.append({"source_url": url, "reason": "Official scholarship page could not be read"})
            continue
        try:
            facts = await _extract(content, actual_url)
        except Exception:
            facts = []
        if not facts:
            unconfirmed.append({"source_url": actual_url, "reason": "No exact cited scholarship facts found"})
            continue
        fields = {fact["field"]: fact for fact in facts}
        scholarships.append({
            "title": fields.get("scholarship.name", {}).get("value") or str(hit.get("title") or "Scholarship"),
            "eligibility": fields.get("scholarship.eligibility"),
            "amount": fields.get("scholarship.amount"),
            "deadline": fields.get("scholarship.deadline"),
            "application_route": fields.get("scholarship.application_route"),
            "source_url": actual_url, "checked_at": checked_now(),
            "status": "unconfirmed", "reason": "A second official observation is needed before these facts are verified",
        })
        break
    return {"scholarships": scholarships, "unconfirmed": unconfirmed}


def get_capabilities():
    return [CapabilityContract(
        id="scholarship.discover", version="1.0.0", name="Scholarship discovery",
        description="Find official scholarships and quote only page-supported eligibility and amounts.",
        input_schema={"type": "object", "properties": {
            "country": {"type": "string"}, "level": {"type": "string"},
            "field": {"type": "string"}}, "required": ["country"]},
        output_schema={"type": "object", "properties": {
            "scholarships": {"type": "array"}, "unconfirmed": {"type": "array"}},
            "required": ["scholarships", "unconfirmed"]},
        handler=discover, owns_task_types=frozenset({"scholarship_discovery"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, vault_scopes=frozenset(),
        permissions=frozenset({"web.read"}),
        required_tools=frozenset({"web.search", "web.fetch", "web.institution_registry"}),
        risk=CapabilityRisk.READ, timeout_seconds=90,
        evidence_expectations={"scholarship_facts": "official URL, exact quote, checked_at; unconfirmed until corroborated"},
    )]
