"""Owns roadmap_research and composes scoped research capabilities."""

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy

DEPENDENCIES = frozenset({
    "program.discover", "program.research", "qualification.recognize",
    "scholarship.discover", "gap.assess",
})


def on_run_status(db, run):
    """Move Counselor stages only from verified run state, never model prose."""
    from app.journey import JourneyService
    from app.counseling.stages import ASSESSING, NEEDS_INFO, PROPOSED, RESEARCHING

    from app.roadmaps.service import RoadmapService
    published = []
    if run.status in {"completed", "needs_user_action", "failed"}:
        published = RoadmapService(db).publish_from_run(run)
    journey = JourneyService(db).ensure_counselor(run.workspace_id, actor="system:research")
    stage = journey.current_stage
    target = None
    if run.status in {"executing", "verifying"} and stage in {RESEARCHING, NEEDS_INFO}:
        target = ASSESSING
    elif (run.status == "needs_user_action" and stage == ASSESSING
          and (run.pending_action or {}).get("type") == "need_from_student"):
        target = NEEDS_INFO
    elif run.status == "completed" and stage == ASSESSING and published:
        target = PROPOSED
    if target:
        JourneyService(db).set_counselor_stage(run.workspace_id, journey.id, target,
                                               actor="system:research")


DIMENSION_PREFIXES = {
    "academics": ("education", "course", "achievement"),
    "English/tests": ("test_attempt", "language_proficiency", "tests"),
    "coursework": ("subject", "coursework", "module", "prerequisite"),
    "finance": ("finance", "financial_sponsor"),
    "timing": ("goal", "application"),
    "documents": ("document", "credential", "certification"),
}


def fit_dimensions(gaps: list[dict]) -> dict:
    dimensions = {name: {"level": "unknown", "reason": "No cited comparable rule yet",
                         "source": None} for name in DIMENSION_PREFIXES}
    weight = {"unknown": 0, "met": 1, "fixable": 2, "blocking": 3}
    for gap in gaps:
        field = str(gap.get("field") or "").casefold()
        for name, prefixes in DIMENSION_PREFIXES.items():
            if any(field.startswith(prefix) for prefix in prefixes):
                current = dimensions[name]
                if weight.get(gap.get("status"), 0) >= weight.get(current["level"], 0):
                    dimensions[name] = {"level": gap.get("status") or "unknown",
                                        "reason": gap.get("reason"),
                                        "source": gap.get("source_url")}
                break
    return dimensions


def _facts(scoped: dict) -> dict:
    from app.memory.student_schema import RECORD_SPECS
    facts = {}
    for domain in (scoped.get("domains") or {}).values():
        if isinstance(domain, dict):
            facts.update(domain.get("facts") or {})
            for field, value in (domain.get("facts") or {}).items():
                if isinstance(value, dict):
                    for key, part in value.items():
                        if isinstance(part, (str, int, float, bool)):
                            facts[f"{field}.{key}"] = part
            for kind, rows in (domain.get("records") or {}).items():
                spec = RECORD_SPECS.get(kind) or {}
                identities = spec.get("identity") or ()
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    identity = ",".join(str(row.get(key) or "") for key in identities)
                    if not identity.strip(","):
                        continue
                    for key, value in row.items():
                        if isinstance(value, (str, int, float, bool)) and value != "":
                            facts[f"{kind}[{identity}].{key}"] = {
                                "value": value,
                                "evidence_level": row.get("verification_status") or "student_reported"}
    return facts


async def build(context, payload):
    from app.config import config
    from app.plugins._shared.budget import bounded_research

    with bounded_research(
        queries=config.PAI_RESEARCH_MAX_QUERIES,
        fetches=config.PAI_RESEARCH_MAX_FETCHES,
        seconds=config.PAI_RESEARCH_MAX_SECONDS,
    ):
        return await _build(context, payload)


async def _build(context, payload):
    brief = payload["brief"]
    stated = str(brief.get("stated_preference") or "").strip()
    objective = str(brief.get("underlying_objective") or "").strip()
    country = str(brief.get("country") or "").strip()
    if not stated or not objective or not country:
        missing = next(key for key, value in (("stated_preference", stated),
                       ("underlying_objective", objective), ("country", country)) if not value)
        field = {"country": "goal.details.target_countries"}.get(missing, f"goal.details.{missing}")
        return {"roadmaps": [], "unconfirmed": [], "pending_action": {
            "type": "need_from_student", "items": [{"field": field,
                "reason": "This changes which routes can be researched", "accepts_upload": False}]}}
    level = str(brief.get("level") or "")
    target = await context.capabilities("program.discover", {
        "objective": stated, "country": country, "level": level})
    alternatives = await context.capabilities("program.discover", {
        "objective": objective, "country": "", "level": level})
    candidates = []
    seen = set()
    refresh_candidate = brief.get("refresh_candidate")
    if isinstance(refresh_candidate, dict) and refresh_candidate.get("url"):
        candidates.append(("stated_goal", refresh_candidate))
        seen.add(refresh_candidate["url"])
    for origin, group in (("stated_goal", target), ("alternative", alternatives)):
        for item in group.get("candidates") or []:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            candidates.append((origin, item))
            if origin == "stated_goal" or sum(kind == "alternative" for kind, _ in candidates) >= 2:
                break
    qualification = await context.capabilities("qualification.recognize", {
        "country": country, "origin_country": brief.get("origin_country") or ""})
    scholarships = await context.capabilities("scholarship.discover", {
        "country": country, "level": level, "field": objective})
    roadmaps = []
    unknown_items = []
    unconfirmed = [*(target.get("unconfirmed") or []),
                   *(alternatives.get("unconfirmed") or []),
                   *(scholarships.get("unconfirmed") or []),
                   *(qualification.get("unconfirmed") or [])]
    for origin, candidate in candidates[:3]:
        research_input = {
            "url": candidate["url"], "country": candidate.get("country") or (country if origin == "stated_goal" else "unknown"),
            "level": candidate.get("level") or level, "intake": candidate.get("intake") or brief.get("intake") or "",
            "route": {"url": candidate["url"], "title": candidate["title"]}}
        if candidate.get("related_urls"):
            research_input["corroborating_url"] = candidate["related_urls"][0]
        researched = await context.capabilities("program.research", research_input)
        unconfirmed.extend(researched.get("unconfirmed") or [])
        requirements = researched.get("requirements") or []
        for requirement in requirements:
            verified = requirement["status"] == "verified"
            # A quoted but unverified threshold is still a lead, not an
            # eligibility rule. Never turn it into a student verdict.
            comparable_rules = requirement["rules"] if verified else []
            assessed = await context.capabilities("gap.assess", {
                "facts": _facts(context.student_context), "rules": comparable_rules})
            unknown_items.extend(assessed["unknowns"])
            gaps = assessed["gaps"]
            levels = {item.get("status") for item in gaps}
            fit = ("weak" if "blocking" in levels else "partial" if levels & {"fixable", "unknown"}
                   else "strong" if levels else "unconfirmed")
            roadmaps.append({
                "origin": origin, "title": candidate["title"],
                "route": {"country": requirement["country"], "level": level,
                          "intake": brief.get("intake"), "url": candidate["url"],
                          "why_suggested": ("Your stated direction" if origin == "stated_goal"
                                            else f"Another route to {objective}")},
                "fit_level": "unconfirmed" if not verified else fit,
                "fit_dimensions": fit_dimensions(gaps),
                "gaps": gaps, "steps": qualification["procedures"],
                "total_cost": None, "time_to_start": brief.get("intake"),
                "risks": (["Requirement facts are still being checked against official sources"]
                          if not verified else []),
                "sources": [{"url": requirement["source_url"],
                             "checked_at": requirement["checked_at"]}],
                "requirement_set_id": requirement["requirement_set_id"],
                "research_status": requirement["status"],
            })
    if unknown_items:
        unique = list({item["field"]: item for item in unknown_items}.values())
        return {"roadmaps": roadmaps, "unconfirmed": unconfirmed, "pending_action": {
            "type": "need_from_student", "items": unique}}
    return {"roadmaps": roadmaps, "unconfirmed": unconfirmed, "pending_action": None}


def get_capabilities():
    return [CapabilityContract(
        id="roadmap.build", version="1.0.0", name="Roadmap research",
        description="Compose cited program research, qualification procedures and deterministic gaps.",
        input_schema={"type": "object", "properties": {
            "brief": {"type": "object"}}, "required": ["brief"]},
        output_schema={"type": "object", "properties": {
            "roadmaps": {"type": "array"}, "unconfirmed": {"type": "array"},
            "pending_action": {}},
            "required": ["roadmaps", "unconfirmed", "pending_action"]},
        handler=build, owns_task_types=frozenset({"roadmap_research"}),
        fallback_policy=FallbackPolicy.FORBIDDEN,
        vault_scopes=frozenset({"education", "goals", "preferences", "finance", "tests"}),
        permissions=frozenset(), required_tools=frozenset(),
        uses_capabilities=DEPENDENCIES, artifacts=frozenset({"roadmap"}),
        risk=CapabilityRisk.READ, timeout_seconds=300,
        evidence_expectations={"roadmaps": "proposed research with source URLs and checked_at"},
        run_status_hook=on_run_status,
    )]
