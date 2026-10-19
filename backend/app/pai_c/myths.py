"""Relevant belief checks: durable, source-attributed, never model-only corrections."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from app.config import config
from app.models import BackgroundJob, CounselorTurnDecision, CounselorNotedQuestion, Workspace
from app.pai_c.memory import MemoryService
from app.pai_c.policy.controller import load_data

JOB_CHECK = "research.claim"


def policy():
    return load_data("myths.json")


def items(db, workspace_id):
    notebook = MemoryService(db).truth_map(workspace_id).notebook
    return [item for part in policy()["item_paths"] for item in getattr(notebook, part)
            if item.status == "active" and item.key.startswith(policy()["item_prefix"])
            and isinstance(item.value, str) and item.value.strip() and item.evidence]


def fingerprint(item):
    return hashlib.sha256(json.dumps([item.id, item.value, item.evidence], ensure_ascii=False).encode()).hexdigest()


def latest_check(db, workspace_id, item):
    return db.scalar(select(BackgroundJob).where(BackgroundJob.workspace_id == workspace_id,
        BackgroundJob.job_type == JOB_CHECK,
        BackgroundJob.payload["fingerprint"].as_string() == fingerprint(item))
        .order_by(BackgroundJob.created_at.desc()).limit(1))


def checked_fact(job):
    from app.pai_c.deep.grounding import current_fact
    fact = (job.result or {}).get("fact") if job and job.status == "succeeded" else None
    return fact if fact and current_fact(fact) else None


def relevant_myth(db, workspace_id, signals):
    if not set(signals.mentioned_areas + ([signals.opened_thread] if signals.opened_thread else [])).intersection(policy()["relevant_areas"]):
        return None
    previous = db.scalars(select(CounselorTurnDecision).where(
        CounselorTurnDecision.workspace_id == workspace_id).order_by(CounselorTurnDecision.source_timestamp.desc())).all()
    for item in sorted(items(db, workspace_id), key=lambda item: item.last_confirmed, reverse=True):
        job = latest_check(db, workspace_id, item)
        bucket = int(datetime.now(timezone.utc).timestamp() // (policy()["retry_hours"] * 3600))
        topic = fingerprint(item) + (":sourced" if checked_fact(job) else f":pending:{bucket}")
        if not any((row.decision or {}).get("action") == "clear_myth" and (row.decision or {}).get("topic") == topic for row in previous):
            return topic
    return None


def selected(db, workspace_id, topic):
    return next((item for item in items(db, workspace_id) if topic.startswith(fingerprint(item) + ":")), None)


def reply(db, workspace_id, topic):
    item = selected(db, workspace_id, topic)
    fact = checked_fact(latest_check(db, workspace_id, item)) if item else None
    if not fact:
        return policy()["checking_reply"]
    return policy()["source_reply"].format(quote=fact["quote"], date=fact["checked_at"][:10], url=fact["source_url"])


def record_answer(db, workspace_id, topic, source_event_id, reply_event_id):
    """Close only the requests whose exact checked claim was actually posted."""
    item = selected(db, workspace_id, topic)
    job = latest_check(db, workspace_id, item) if item else None
    fact = checked_fact(job)
    if not fact:
        return
    for row in db.scalars(select(CounselorNotedQuestion).where(
            CounselorNotedQuestion.workspace_id == workspace_id,
            CounselorNotedQuestion.source_event_id.in_([source_event_id, job.payload.get('source_event_id')]),
            CounselorNotedQuestion.question_to_research == item.value,
            CounselorNotedQuestion.status.in_(['open', 'unanswered']))):
        row.status = 'answered'
        row.answered_event_id = reply_event_id
        row.answer = fact
    db.commit()


def enqueue_check(db, workspace_id, topic, source_event_id):
    from app.runtime.task_runtime import enqueue
    from app.pai_c.deep.noted_questions import NotedQuestionService
    item = selected(db, workspace_id, topic)
    if item is None:
        return None
    NotedQuestionService(db).record(workspace_id, source_event_id, item.value, needs_research=True)
    prior = latest_check(db, workspace_id, item)
    now = datetime.now(timezone.utc)
    if prior:
        created = prior.created_at.replace(tzinfo=timezone.utc) if prior.created_at.tzinfo is None else prior.created_at
        if prior.status in {"pending", "running"} or checked_fact(prior) or now < created + timedelta(hours=policy()["retry_hours"]):
            return prior
    key = f"myth:{workspace_id}:{fingerprint(item)}" + (f":retry:{prior.id}" if prior else "")
    job = enqueue(db, job_type=JOB_CHECK, workspace_id=workspace_id,
        payload={"fingerprint": fingerprint(item), "source_event_id": source_event_id}, idempotency_key=key)
    db.commit()
    return job


class ClaimPassage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    quote: str
    source_url: str


async def check_job(job, db):
    from app.inference.gateway import complete
    from app.pai_c.deep.prompts import load_prompt
    from app.pai_c.deep.polish import contains_blocked_script
    from app.plugins._shared.budget import bounded_research, spend, record_model_usage
    from app.plugins._shared.sources import data, public_https
    from app.plugins._shared.verification import SourceVerifier
    from app.tools import ToolContext, AUDIENCE_COUNSELOR, get_tool_executor
    from app.services.pai import PAI_AGENT_NAME, WorkspaceApi
    from app.research.requirements import RequirementStore
    item = next((item for item in items(db, job.workspace_id) if fingerprint(item) == job.payload.get("fingerprint")), None)
    workspace = db.get(Workspace, job.workspace_id)
    if not item or not workspace or workspace.status != "active":
        return {"status": "superseded"}
    rules = policy()
    claim = item.value
    ctx = ToolContext(workspace_id=job.workspace_id, agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(job.workspace_id, workspace.password_hash), audience=AUDIENCE_COUNSELOR,
        allowed_tools=frozenset({"web.search", "web.fetch"}),
        granted_capabilities=MemoryService(db).agent_capabilities(PAI_AGENT_NAME))
    db.rollback()
    pages = []
    # A separate bounded window avoids consuming a future Mirror's allowance or
    # locking the student out of belief checks for the lifetime of the workspace.
    period = int(datetime.now(timezone.utc).timestamp() // (rules['budget_period_days'] * 86400))
    with bounded_research(queries=1, fetches=rules["fetch_limit"], seconds=config.PAI_RESEARCH_MAX_SECONDS,
            workspace_id=job.workspace_id, mirror_version=f"belief_checks:{period}") as budget:
        found = data(await get_tool_executor().execute("web.search", {"query": rules["query"].format(claim=claim), "limit": rules["search_limit"]}, ctx))
        for hit in (found.get("results") or [])[:rules["fetch_limit"]]:
            if not public_https(hit.get("url")):
                continue
            page = data(await get_tool_executor().execute("web.fetch", {"url": hit["url"], "max_chars": rules["page_chars"]}, ctx))
            url = page.get("url", hit["url"])
            if page.get("content") and public_https(url):
                pages.append({"url": url, "text": page["content"]})
        if not pages:
            return {"status": "unanswered", "research_metrics": budget.usage()}
        exhausted = spend("model")
        if exhausted:
            return {"status": "unanswered", "research_metrics": budget.usage()}
        raw = await complete("research_extract", system_prompt=load_prompt("myth_check"),
            messages=[{"role": "user", "content": json.dumps({"claim": claim, "pages": pages,
                "language_policy": {"blocked_scripts": config.PAI_LANGUAGE_BLOCKED_SCRIPTS}})}],
            response_format={"type": "json_object"}, max_tokens=rules["max_tokens"],
            phase="myth_check", turn_id=job.payload.get("source_event_id"), usage_callback=record_model_usage)
        try:
            passage = ClaimPassage.model_validate_json(raw)
        except ValueError:
            return {"status": "unanswered", "research_metrics": budget.usage()}
        page = next((page for page in pages if page["url"] == passage.source_url and passage.quote and passage.quote in page["text"]), None)
        if not page or contains_blocked_script(passage.quote, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            return {"status": "unanswered", "research_metrics": budget.usage()}
        checked = datetime.now(timezone.utc)
        fact = {"field": "belief", "value": passage.quote, "quote": passage.quote,
            "source_url": passage.source_url, "checked_at": checked.isoformat(), "kind": "explanation"}
        store = RequirementStore(db)
        institution = store.institution_for_url(passage.source_url)
        domains = set(rules["trusted_domains"]) | store.official_domains(institution)
        verdict = SourceVerifier(freshness_days=rules["cache_days"]).verify(claims=[fact], source_url=passage.source_url,
            official_domains=domains, intake=None, page_text=page["text"], checked_at=checked)
        # Agreement is an admissions-number check; this is a verbatim qualitative
        # source attribution, never a calculated eligibility rule.
        verified = all(verdict.checks[key]["passed"] for key in rules["required_checks"])
        return {"status": "sourced" if verified else "unanswered", "fact": {**fact, "status": "verified"} if verified else None,
            "research_metrics": budget.usage()}
