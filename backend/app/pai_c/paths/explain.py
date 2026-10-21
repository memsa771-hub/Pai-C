"""Typed path explanation owned by an Operator workflow capability."""
import json
from pathlib import Path
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from app.workspace_language import workspace_language
from app.config import config
from app.inference.gateway import complete
from app.pai_c.deep.polish import contains_blocked_script
from app.plugins._shared.sources import data, public_https, cited_facts
from app.plugins._shared.verification import SourceVerifier
from app.plugins._shared.budget import bounded_research, spend, record_model_usage


def policy():
    return json.loads(Path(__file__).with_name("policy.json").read_text(encoding="utf-8"))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fit(Strict):
    observation: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class WorldFact(Strict):
    field: str
    value: str
    quote: str
    source_url: str


class PathExplanation(Strict):
    what_it_is: str = Field(min_length=1)
    what_you_study: list[str]
    work_day: str = Field(min_length=1)
    skills: list[str]
    fit_for: list[Fit]
    fit_against: list[Fit]
    ways_in: list[str]
    try_it: str = Field(min_length=1)
    world_facts: list[WorldFact]


def validate_explanation(raw, brief):
    result = PathExplanation.model_validate_json(raw)
    if contains_blocked_script(result.model_dump_json(), config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
        raise ValueError("Blocked script in explanation")
    evidence = {item["text"] for item in brief["evidence"] if isinstance(item, dict) and item.get("text")}
    if any(item.evidence not in evidence for item in [*result.fit_for, *result.fit_against]):
        raise ValueError("Fit must cite the student's actual evidence")
    return result


async def explain(context, payload):
    brief = payload["brief"]
    rules = policy()
    pages = []
    with bounded_research(queries=config.PAI_RESEARCH_MAX_QUERIES,
        fetches=config.PAI_RESEARCH_MAX_FETCHES, seconds=config.PAI_RESEARCH_MAX_SECONDS,
        workspace_id=context.workspace_id, mirror_version=brief["mirror_version"]) as budget:
        found = data(await context.tools.invoke("web.search", {"query": rules["query"].format(field=brief["title"]), "limit": rules["search_limit"]}))
        for hit in (found.get("results") or [])[:rules["fetch_limit"]]:
            url = hit.get("url")
            if not public_https(url):
                continue
            page = data(await context.tools.invoke("web.fetch", {"url": url, "max_chars": rules["page_chars"]}))
            if page.get("content") and public_https(page.get("url", url)):
                pages.append({"url": page.get("url", url), "text": page["content"][:rules["page_chars"]]})
        failure = spend("model")
        if failure:
            raise ValueError(failure)
        raw = await complete(role="roadmap", phase="path_explain",
            system_prompt=Path(__file__).with_name("explain.md").read_text(encoding="utf-8"),
            messages=[{"role": "user", "content": json.dumps({"path": brief, "pages": pages,
                "schema": PathExplanation.model_json_schema(), "workspace_language": workspace_language(), "language_policy": {
                    "blocked_scripts": config.PAI_LANGUAGE_BLOCKED_SCRIPTS,
                    "replacement": config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT}}, ensure_ascii=False)}],
            response_format={"type": "json_object"}, max_tokens=rules["max_tokens"], usage_callback=record_model_usage)
        explanation = validate_explanation(raw, brief)
        checked = datetime.now(timezone.utc)
        sources, unconfirmed = [], []
        for page in pages:
            facts = cited_facts([item.model_dump() for item in explanation.world_facts if item.source_url == page["url"]], page["text"], page["url"], checked.isoformat())
            if not facts:
                continue
            verdict = SourceVerifier(freshness_days=config.PAI_RESEARCH_FRESHNESS_DAYS).verify(
                claims=facts, source_url=page["url"], official_domains=set(rules["trusted_domains"]),
                intake=None, page_text=page["text"], checked_at=checked)
            destination = sources if verdict.status == "verified" else unconfirmed
            destination.extend({**item, "status": verdict.status} for item in facts)
        public = explanation.model_dump(exclude={"world_facts"})
        return {"path": public, "possibility_id": brief["possibility_id"], "mirror_version": brief["mirror_version"],
            "facts": sources, "unconfirmed": unconfirmed,
            "missing": [] if sources else [rules["missing_sources"]],
            "summary": rules["summary"], "research_metrics": budget.usage()}


def current_path_result(result):
    from app.pai_c.deep.grounding import current_fact
    facts = [fact for fact in result.get('facts', []) if current_fact(fact)]
    expired = len(facts) != len(result.get('facts', []))
    return {**result, 'facts': facts,
        'missing': list(dict.fromkeys([*result.get('missing', []), *([policy()['missing_sources']] if expired else [])]))}, expired
