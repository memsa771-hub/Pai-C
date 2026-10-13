"""Build lane artifacts from the confirmed Mirror and cited public evidence."""

import json
import logging
import re
from pydantic import BaseModel, Field, ValidationError

from app.config import config
from app.pai_c.deep.polish import contains_blocked_script
from app.pai_c.deep.prompts import load_prompt
from app.inference.gateway import complete as chat_completion, resolve_model
from app.plugins._shared.sources import public_https

logger = logging.getLogger(__name__)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
FIT_FIELDS = ("why_for_you", "strengths_used", "weakness_guarded", "family_fit",
              "real_why_fit", "constraints_fit", "test_30_days")


class RoadmapCandidate(BaseModel):
    title: str = ""
    why_for_you: str = ""
    strengths_used: list[str] = Field(default_factory=list)
    weakness_guarded: str = ""
    family_fit: str = ""
    real_why_fit: str = ""
    constraints_fit: str = ""
    test_30_days: str = ""
    gap: list[dict[str, str]] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    facts: list[dict] = Field(default_factory=list)
    citations: dict[str, list[str]] = Field(default_factory=dict)
    status: str = "needs_info"


def lanes_for_mirror(mirror):
    # Validation and regeneration belong to the Mirror job. Research preserves
    # the student's confirmed lanes, without modifying them or failing later.
    return [dict(item) for item in mirror.get("roadmap_lanes") or []]


def fact_index(research):
    groups = [*(research.get("lanes") or []), {"facts": research.get("question_facts") or []}]
    return {fact["fact_id"]: fact for item in groups
            for fact in item.get("facts") or [] if fact.get("fact_id") and
            fact.get("quote") and public_https(fact.get("source_url"))}


def _strings(value, prefix=""):
    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{prefix}.{index}".strip("."))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"fact_id", "fact_ids", "source", "source_url", "url", "label"}:
                yield from _strings(item, f"{prefix}.{key}".strip("."))


def ground_roadmap(candidate, lane, facts, research, student_data=None):
    candidate = candidate if isinstance(candidate, dict) else {}
    missing = []
    try:
        candidate = RoadmapCandidate.model_validate(candidate).model_dump()
    except ValidationError:
        candidate = RoadmapCandidate().model_dump()
        missing.append({"field": "roadmap", "reason": "invalid_schema"})
    citations = candidate.get("citations") or {}
    if not isinstance(citations, dict):
        citations = {}
    used = set()
    own_numbers = set(_NUMBER.findall(json.dumps(student_data or {}, default=str)))
    fields = {key: candidate.get(key, [] if key == "strengths_used" else "") for key in FIT_FIELDS}
    fields.update(title=candidate.get("title") or lane["why"],
        gap=candidate.get("gap") or [], steps=candidate.get("steps") or [],
        risks=candidate.get("risks") or [], facts=candidate.get("facts") or [])
    for key in FIT_FIELDS:
        if key != "strengths_used" and not fields[key].strip():
            missing.append({"field": key, "reason": "missing_student_fit"})
    for path, text in _strings(fields):
        ids = citations.get(path) or []
        if not isinstance(ids, list): ids = []
        refs = [facts[item] for item in ids if isinstance(item, str) and item in facts]
        world_field = (path.startswith("facts.") or
            (path.startswith("gap.") and path.endswith(".need")) or
            (path.startswith("steps.") and path.endswith(".when")))
        personal_field = path.split(".")[0] in FIT_FIELDS or (
            path.startswith("gap.") and path.endswith(".have"))
        numbers = set(_NUMBER.findall(text))
        external_numbers = numbers if world_field or not personal_field else numbers - own_numbers
        if path == "test_30_days":
            external_numbers = set()  # Self-set action targets, never outside-world requirements.
        required = world_field or bool(external_numbers)
        if required and not refs:
            missing.append({"field": path, "reason": "missing_research_fact"})
        if refs:
            supported = {number for fact in refs for number in _NUMBER.findall(
                json.dumps({"quote": fact["quote"], "value": fact.get("value")}, ensure_ascii=True))}
            if any(number not in supported for number in external_numbers):
                missing.append({"field": path, "reason": "unsupported_number"})
            else:
                used.update(item for item in ids if item in facts)
    lane_facts = next((item.get("facts") or [] for item in research.get("lanes") or []
                       if item["lane"] == lane["lane"]), [])
    covered = {fact.get("decisive_field") for fact in lane_facts
               if fact.get("fact_id") in used and fact.get("fact_id") in facts}
    for field in research.get("decisive_fields") or []:
        if field not in covered:
            missing.append({"field": field, "reason": "missing_decisive_fact"})
    if not lane_facts or not used:
        missing.append({"field": "decisive_facts", "reason": "missing_research_fact"})
    if contains_blocked_script(json.dumps(fields, ensure_ascii=False), config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
        # A broken-script artifact is never sent to the UI, even as needs_info.
        fields = {key: ([] if key == "strengths_used" else "") for key in FIT_FIELDS}
        fields.update(title="", gap=[], steps=[], risks=[], facts=[])
        missing.append({"field": "language_policy", "reason": "blocked_script"})
        missing.append({"field": "decisive_facts", "reason": "missing_decisive_fact"})
    # Remove unsupported text rather than publishing a false claim under a warning.
    for item in missing:
        if item.get("reason") in {"unsupported_number", "missing_research_fact"}:
            path = item["field"].split(".")
            parent = fields
            try:
                for key in path[:-1]: parent = parent[int(key)] if isinstance(parent, list) else parent[key]
                if isinstance(parent, list): parent[int(path[-1])] = ""
                else: parent[path[-1]] = ""
            except (KeyError, IndexError, TypeError, ValueError):
                pass
    sources = [{"fact_id": item, "url": facts[item]["source_url"],
                "checked_at": facts[item]["checked_at"], "status": facts[item]["label"],
                "quote": facts[item]["quote"]} for item in sorted(used)]
    for index, item in enumerate(fields.get("facts") or []):
        if isinstance(item, dict):
            refs = [facts[key] for key in citations.get(f"facts.{index}.text", []) if key in facts]
            if refs:
                item["label"] = "verified" if all(ref.get("label") == "verified" for ref in refs) else "unconfirmed"
    return {**fields, "title": fields.get("title") or "", "lane": lane["lane"],
        "origin": lane["lane"] if lane["lane"] in {"stated_goal", "family_wish"} else "alternative",
        "route": {"url": sources[0]["url"]} if sources else {},
        "sources": sources, "citations": citations, "missing_facts": missing,
        "generation_status": "needs_info" if any(item["reason"] == "missing_decisive_fact"
            or item["field"] == "decisive_facts" for item in missing) else "ready",
        "requirement_set_id": next((facts[item].get("requirement_set_id") for item in used), None)}


async def build_mirror_roadmaps(brief, research):
    custom = brief.get("custom_roadmap")
    lanes = ([{"lane": "student_added", "why": custom["title"]}] if custom else lanes_for_mirror(brief["mirror"]))
    facts = fact_index(research)
    raw = None
    try:
        from app.plugins._shared.budget import spend, record_model_usage
        if spend("model"):
            raise ValueError("research_student_budget_exceeded")
        raw = await chat_completion(role="roadmap", api_key=config.PAI_API_KEY, model=resolve_model("roadmap"),
            system_prompt=load_prompt("roadmap_builder"), response_format={"type": "json_object"},
            messages=[{"role": "user", "content": json.dumps({
                "mirror": {**brief["mirror"], "roadmap_lanes": lanes}, "notebook": brief["notebook"],
                "profile": brief["profile"], "research": research,
                "language_policy": {"blocked_scripts": config.PAI_LANGUAGE_BLOCKED_SCRIPTS,
                    "replacement": config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT}}, default=str)}],
            reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT, base_url=config.PAI_BASE_URL,
            usage_callback=record_model_usage)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict): raise ValueError("invalid roadmap object")
    except Exception as exc:
        logger.warning("roadmap_builder_failed error_type=%s", type(exc).__name__)
        parsed = {}
    candidates = {item.get("lane"): item for item in parsed.get("roadmaps") or [] if isinstance(item, dict)}
    student_data = {key: brief.get(key) or {} for key in ("notebook", "profile", "mirror")}
    roadmaps = [ground_roadmap(candidates.get(lane["lane"], {}), lane, facts, research, student_data) for lane in lanes]
    answers = []
    for answer in parsed.get("question_answers") or []:
        if not isinstance(answer, dict): continue
        fact = facts.get(answer.get("fact_id"))
        question = next((item for item in brief.get("questions") or [] if item["id"] == answer.get("question_id")), None)
        if not fact or not question or fact.get("label") != "verified": continue
        if contains_blocked_script(fact["quote"], config.PAI_LANGUAGE_BLOCKED_SCRIPTS): continue
        # Render the exact public quote as the answer, not uncited generated prose.
        answers.append({"question_id": question["id"], "fact_id": fact["fact_id"],
            "answer": fact["quote"], "source_url": fact["source_url"], "label": fact["label"]})
    return {"roadmaps": roadmaps, "question_answers": answers, "light_research": research,
            "unconfirmed": research.get("missing") or [], "pending_action": None,
            "mirror_version": brief["mirror_version"]}
