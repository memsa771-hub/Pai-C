"""Extract auditable proposed requirements from a fetched source page."""

import json
from datetime import datetime

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import checked_now, cited_facts, data, public_https
from app.plugins._shared.verification import official_url


EXTRACTION_PROMPT = (
    "Extract only explicit programme admission facts from the supplied official page. "
    "Return a JSON object with a facts array. Each fact is "
    "{field,value,quote,kind,category,comparator,threshold,unit,scale}. "
    "Cover entry qualification, minimum grades, required subjects or coursework, "
    "language proficiency and other tests, documents, application route, deadline by intake, "
    "tuition, other stated costs, and language of instruction only when shown. "
    "For a fee, value must be {amount:number,currency:ISO_4217,basis:per_year|per_semester|total|per_credit}; "
    "for a deadline, value must be an ISO date. Fee category is tuition, living, or other. "
    "Do not invent missing units, dates, or exchange rates. "
    "kind is requirement, fee, deadline, or intake. Comparator is gte, lte, or eq only "
    "when a threshold is explicit. For a student-comparable rule use a field key "
    "from the canonical list; replace angle-bracket identity placeholders with the "
    "explicit qualification or test name. Otherwise retain the page term and omit comparator. "
    "Quote must be an exact contiguous excerpt. No inference or student profile facts. "
    "Use an empty array when unclear."
    " When focus is supplied, extract only the decisive fields and answers to its questions."
    " Tag each fact with decisive_field from the supplied fields, or question, and question_ids for questions it directly answers."
)


async def _extract_page(content, url, payload, comparison_fields, checked_at):
    from app.config import config
    from app.inference.gateway import complete as chat_completion, resolve_model
    from app.plugins._shared.budget import spend, record_model_usage
    if spend("model"):
        raise ValueError("research_student_budget_exceeded")

    raw = await chat_completion(role="research_extract",
        api_key=config.PAI_API_KEY, model=resolve_model("research_extract"),
        system_prompt=EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": json.dumps({
            "country": payload["country"], "level": payload.get("level"),
            "intake": payload.get("intake"), "source_url": url,
            "comparison_fields": comparison_fields,
            "focus": payload.get("focus"),
            "page": content[:18000]}, ensure_ascii=False)}],
        max_tokens=2200, base_url=config.PAI_BASE_URL or None,
        usage_callback=record_model_usage,
    )
    parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    return cited_facts(parsed.get("facts") or [], content, url, checked_at)


async def research(context, payload):
    url = payload["url"]
    if not public_https(url):
        return {"requirements": [], "unconfirmed": [{"reason": "Invalid source URL"}]}
    from app.database import new_session
    from app.research.requirements import RequirementStore
    with new_session() as cache_db:
        cached = RequirementStore(cache_db).cached(context.workspace_id, payload)
        if cached:
            cache_db.commit()
            return {"requirements": [cached], "unconfirmed": []}
    fetched = data(await context.tools.invoke("web.fetch", {"url": url, "max_chars": 20000}))
    content = str(fetched.get("content") or "")
    actual_url = str(fetched.get("url") or url)
    if not content or not public_https(actual_url):
        return {"requirements": [], "unconfirmed": [{"reason": "Source page unavailable", "url": url}]}
    checked_at = checked_now()
    from app.database import new_session
    from app.memory.field_definitions import VaultFieldDefinitionService
    from app.memory.student_schema import RECORD_SPECS
    catalog_db = new_session()
    try:
        definitions = VaultFieldDefinitionService(catalog_db).list_definitions()
        comparison_fields = [item.key for item in definitions]
        comparison_fields.extend(
            f"{item.key}.{key}" for item in definitions
            for key, shape in (item.validation_schema or {}).get("properties", {}).items()
            if shape.get("type") in {"string", "number", "integer"}
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
        facts = await _extract_page(content, actual_url, payload, comparison_fields, checked_at)
    except Exception:
        facts = []
    if not facts:
        return {"requirements": [], "unconfirmed": [{"reason": "No exact cited requirements extracted", "url": actual_url}]}
    from app.research.requirements import RequirementStore
    db = new_session()
    try:
        store = RequirementStore(db)
        institution = store.institution_for_url(actual_url)
        if institution is None:
            identity = data(await context.tools.invoke(
                "web.institution_registry", {"url": actual_url})).get("identity")
            if identity:
                institution = store.register_provider_identity(identity)
        secondary_facts = []
        secondary_at = None
        secondary_url = payload.get("corroborating_url")
        if (secondary_url and institution and secondary_url != actual_url and
                official_url(secondary_url, store.official_domains(institution))):
            secondary_page = data(await context.tools.invoke(
                "web.fetch", {"url": secondary_url, "max_chars": 20000}))
            secondary_content = str(secondary_page.get("content") or "")
            actual_secondary_url = str(secondary_page.get("url") or secondary_url)
            if (secondary_content and actual_secondary_url != actual_url and
                    official_url(actual_secondary_url, store.official_domains(institution))):
                secondary_at = datetime.fromisoformat(checked_now())
                try:
                    secondary_facts = await _extract_page(
                        secondary_content, actual_secondary_url, payload,
                        comparison_fields, secondary_at.isoformat())
                except Exception:
                    secondary_facts = []
        question_links = {(fact["field"], fact["quote"]): fact.get("question_ids") or [] for fact in facts}
        public_facts = [{key: value for key, value in fact.items() if key != "question_ids"} for fact in facts]
        rules = [fact for fact in public_facts if fact.get("kind") not in {"fee", "deadline"}]
        fees = {fact["field"]: fact for fact in public_facts if fact.get("kind") == "fee"}
        deadlines = {fact["field"]: fact for fact in public_facts if fact.get("kind") == "deadline"}
        opportunity, requirement_set = store.propose(
            context.workspace_id, route=payload.get("route") or {"url": actual_url},
            country=payload["country"], level=payload.get("level"),
            intake=payload.get("intake"), institution=institution,
            source_url=actual_url, checked_at=datetime.fromisoformat(checked_at),
            rules=rules, fees=fees, deadlines=deadlines, page_text=content,
            corroboration=secondary_facts, corroborated_at=secondary_at,
            public_facts=True,
        )
        result = {"opportunity_id": opportunity.id, "requirement_set_id": requirement_set.id,
                  "status": requirement_set.status, "verification_checks": requirement_set.verification_checks,
                  "rules": rules, "fees": fees,
                  "deadlines": deadlines, "source_url": actual_url,
                  "checked_at": checked_at, "country": payload["country"],
                  "level": payload.get("level"), "intake": payload.get("intake"),
                  "corroborating_source_url": (actual_secondary_url if secondary_facts else None),
                  "corroborated_at": secondary_at.isoformat() if secondary_facts and secondary_at else None}
        db.commit()
        result = {**result, **store.payload(opportunity, requirement_set)}
        for fact in [*result["rules"], *result["fees"].values(), *result["deadlines"].values()]:
            fact["question_ids"] = question_links.get((fact["field"], fact["quote"]), [])
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
            "institution": {"type": "string"}, "route": {"type": "object"},
            "corroborating_url": {"type": "string"}, "focus": {"type": "object"}},
            "required": ["url", "country"]},
        output_schema={"type": "object", "properties": {
            "requirements": {"type": "array"}, "unconfirmed": {"type": "array"}},
            "required": ["requirements", "unconfirmed"]},
        handler=research, owns_task_types=frozenset({"program_research"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, vault_scopes=frozenset(),
        permissions=frozenset({"web.read"}),
        required_tools=frozenset({"web.fetch", "web.institution_registry"}),
        risk=CapabilityRisk.READ, timeout_seconds=90,
        evidence_expectations={"claims": "exact source quote, HTTPS URL, checked_at, proposed status"},
    )]
