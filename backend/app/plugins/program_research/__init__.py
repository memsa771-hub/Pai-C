"""Extract auditable proposed requirements from a fetched source page."""

import json
from datetime import datetime

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import checked_now, cited_facts, data, public_https


async def research(context, payload):
    url = payload["url"]
    if not public_https(url):
        return {"requirements": [], "unconfirmed": [{"reason": "Invalid source URL"}]}
    fetched = data(await context.tools.invoke("web.fetch", {"url": url, "max_chars": 20000}))
    content = str(fetched.get("content") or "")
    actual_url = str(fetched.get("url") or url)
    if not content or not public_https(actual_url):
        return {"requirements": [], "unconfirmed": [{"reason": "Source page unavailable", "url": url}]}
    checked_at = checked_now()
    from app.config import config
    from app.database import new_session
    from app.inference.client import chat_completion
    from app.memory.field_definitions import VaultFieldDefinitionService
    from app.memory.field_definitions import ENTITY_BACKED_LEGACY_FIELDS
    from app.memory.student_schema import RECORD_SPECS
    catalog_db = new_session()
    try:
        definitions = VaultFieldDefinitionService(catalog_db).list_definitions()
        comparison_fields = [item.key for item in definitions
                             if item.key not in ENTITY_BACKED_LEGACY_FIELDS]
        comparison_fields.extend(
            f"{item.key}.{key}" for item in definitions
            for key, shape in (item.validation_schema or {}).get("properties", {}).items()
            if item.key not in ENTITY_BACKED_LEGACY_FIELDS
            and shape.get("type") in {"string", "number", "integer"}
        )
        comparison_fields.extend(
            f"{kind}[<{','.join(spec['identity'])}>].{field}"
            for kind, spec in RECORD_SPECS.items()
            for field, shape in spec["properties"].items()
            if field not in spec["identity"] and shape.get("type") in {"string", "number", "integer"}
        )
    finally:
        catalog_db.close()
    try:
        raw = await chat_completion(
            api_key=config.PAI_API_KEY, model=config.PAI_MODEL,
            system_prompt=("Extract only explicit admission requirements, fees, deadlines and intake from "
                           "the supplied page. Return JSON object with facts array of "
                           "{field,value,quote,kind,comparator,threshold}. "
                           "kind is requirement, fee, deadline, or intake. Comparator is gte, lte, "
                           "or eq only when the threshold is explicit. "
                           "For a student-comparable rule, use a field key from the supplied canonical "
                           "field list. Replace the angle bracket identity placeholder with the "
                           "explicit qualification or test name from the page (for example IELTS). "
                           "If none fits, retain the page's term and omit comparator. "
                           "Quote must be an exact contiguous excerpt. "
                           "No inference, no profile facts, no unsourced values. Use an empty array if unclear."),
            messages=[{"role": "user", "content": json.dumps({
                "country": payload["country"], "level": payload.get("level"),
                "intake": payload.get("intake"), "source_url": actual_url,
                "comparison_fields": comparison_fields,
                "page": content[:18000]}, ensure_ascii=False)}],
            max_tokens=1800, base_url=config.PAI_BASE_URL or None,
        )
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        facts = cited_facts(parsed.get("facts") or [], content, actual_url, checked_at)
    except Exception:
        facts = []
    if not facts:
        return {"requirements": [], "unconfirmed": [{"reason": "No exact cited requirements extracted", "url": actual_url}]}
    from app.research.requirements import RequirementStore
    db = new_session()
    try:
        rules = [fact for fact in facts if fact.get("kind") not in {"fee", "deadline"}]
        fees = {fact["field"]: fact for fact in facts if fact.get("kind") == "fee"}
        deadlines = {fact["field"]: fact for fact in facts if fact.get("kind") == "deadline"}
        opportunity, requirement_set = RequirementStore(db).propose(
            context.workspace_id, route=payload.get("route") or {"url": actual_url},
            country=payload["country"], level=payload.get("level"),
            intake=payload.get("intake"), institution=payload.get("institution"),
            source_url=actual_url, checked_at=datetime.fromisoformat(checked_at),
            rules=rules, fees=fees, deadlines=deadlines,
        )
        result = {"opportunity_id": opportunity.id, "requirement_set_id": requirement_set.id,
                  "status": "proposed", "rules": rules, "fees": fees,
                  "deadlines": deadlines, "source_url": actual_url,
                  "checked_at": checked_at, "country": payload["country"],
                  "level": payload.get("level"), "intake": payload.get("intake")}
        db.commit()
    finally:
        db.close()
    return {"requirements": [result], "unconfirmed": []}


def get_capabilities():
    return [CapabilityContract(
        id="program.research", version="1.0.0", name="Program research",
        description="Fetch a program page and propose only claims with exact source quotations.",
        input_schema={"type": "object", "properties": {
            "url": {"type": "string"}, "country": {"type": "string"},
            "level": {"type": "string"}, "intake": {"type": "string"},
            "institution": {"type": "string"}, "route": {"type": "object"}},
            "required": ["url", "country"]},
        output_schema={"type": "object", "properties": {
            "requirements": {"type": "array"}, "unconfirmed": {"type": "array"}},
            "required": ["requirements", "unconfirmed"]},
        handler=research, owns_task_types=frozenset({"program_research"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, vault_scopes=frozenset(),
        permissions=frozenset({"web.read"}), required_tools=frozenset({"web.fetch"}),
        risk=CapabilityRisk.READ, timeout_seconds=90,
        evidence_expectations={"claims": "exact source quote, HTTPS URL, checked_at, proposed status"},
    )]
