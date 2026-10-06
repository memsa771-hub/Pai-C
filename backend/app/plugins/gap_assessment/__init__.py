"""Pure, deterministic comparison of accepted or reported facts and cited rules."""

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy
from app.plugins._shared.sources import public_https


def assess_rule(rule: dict, facts: dict) -> dict:
    field = str(rule.get("field") or "")
    source = str(rule.get("source_url") or "")
    base = {"field": field, "rule": rule, "source_url": source,
            "status": "unknown", "reason": "No comparable fact or cited rule"}
    if not field or not public_https(source) or not rule.get("checked_at"):
        return base
    observed = {str(key).casefold(): value for key, value in facts.items()}.get(field.casefold())
    if observed is None:
        return {**base, "reason": "Student fact missing", "accepts_upload": True}
    value = observed.get("value") if isinstance(observed, dict) else observed
    evidence = observed.get("evidence_level", "student_reported") if isinstance(observed, dict) else "student_reported"
    op = rule.get("comparator")
    threshold = rule.get("threshold")
    if op not in {"gte", "lte", "eq"} or threshold is None:
        return {**base, "reason": "Requirement has no machine-comparable threshold"}
    try:
        if op in {"gte", "lte"}:
            matched = float(value) >= float(threshold) if op == "gte" else float(value) <= float(threshold)
        else:
            matched = str(value).casefold() == str(threshold).casefold()
    except (TypeError, ValueError):
        return {**base, "reason": "Student fact cannot be compared to the rule"}
    if matched:
        return {**base, "status": "met", "reason": "Reported value meets the cited threshold",
                "student_evidence": evidence}
    remediation = rule.get("remediation")
    if isinstance(remediation, dict) and remediation.get("action") and remediation.get("source_url"):
        return {**base, "status": "fixable", "reason": "Cited remediation is available",
                "student_evidence": evidence, "remediation": remediation,
                "time_to_fix": remediation.get("time_to_fix")}
    return {**base, "status": "blocking", "reason": "Reported value does not meet the cited threshold",
            "student_evidence": evidence}


async def assess(context, payload):
    results = [assess_rule(rule, payload["facts"]) for rule in payload["rules"]]
    return {"gaps": results,
            "unknowns": [{"field": item["field"], "reason": item["reason"],
                          "accepts_upload": item.get("accepts_upload", False)}
                         for item in results if item["status"] == "unknown"
                         and item.get("accepts_upload")]}


def get_capabilities():
    return [CapabilityContract(
        id="gap.assess", version="1.0.0", name="Gap assessment",
        description="Deterministically compare student facts with cited program rules.",
        input_schema={"type": "object", "properties": {
            "facts": {"type": "object"}, "rules": {"type": "array"}},
            "required": ["facts", "rules"]},
        output_schema={"type": "object", "properties": {
            "gaps": {"type": "array"}, "unknowns": {"type": "array"}},
            "required": ["gaps", "unknowns"]},
        handler=assess, owns_task_types=frozenset({"gap_assessment"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, vault_scopes=frozenset(),
        permissions=frozenset(), required_tools=frozenset(), risk=CapabilityRisk.READ,
        timeout_seconds=10, evidence_expectations={"each_gap": "rule and source URL"},
    )]
