"""Fail closed on declared world claims and unsupported numeric world claims."""
import json
import re
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, ConfigDict, Field
from app.config import config
from app.pai_c.policy.controller import load_data
from app.plugins._shared.sources import public_https


class WorldClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1)
    fact_ids: list[str] = Field(min_length=1)


def current_fact(fact):
    rules = load_data("grounding.json")
    if fact.get("status") not in rules["source_statuses"] or not public_https(fact.get("source_url")):
        return False
    try:
        checked = datetime.fromisoformat(str(fact.get("checked_at") or "").replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return checked.tzinfo is not None and now - timedelta(days=config.PAI_RESEARCH_FRESHNESS_DAYS) <= checked <= now
    except (TypeError, ValueError):
        return False


def allowed_context(context_text: str) -> str:
    """The text of the context sections a reply may restate without a world
    source (grounding.json allowed_sections): the student's own facts and
    PAI's description of itself (<about_pai>)."""
    names = "|".join(re.escape(name) for name in load_data("grounding.json")["allowed_sections"])
    return " ".join(body for _, body in re.findall(rf"<({names})>(.*?)</\1>", context_text, flags=re.DOTALL))


def guard_reply(reply, raw, facts, student_context):
    rules = load_data("grounding.json")
    index = {str(row["fact_id"]): row for row in facts if row.get("fact_id") and current_fact(row)}
    try:
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        claims = parsed.get("world_claims", []) if isinstance(parsed, dict) else []
    except (ValueError, TypeError):
        claims = []
    if not isinstance(claims, list):
        return rules["checking_reply"], ["invalid_world_claim"]
    violations, allowed_spans = [], []
    for item in claims if isinstance(claims, list) else []:
        text = item.get("text") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text or text not in reply:
            return rules["checking_reply"], ["invalid_world_claim"]
        try:
            claim = WorldClaim.model_validate(item)
            sources = [index[key] for key in claim.fact_ids]
            # Model paraphrases are not independent evidence. Quoted facts may
            # be explained around, but the sourced assertion stays exact.
            valid = any(claim.text == row.get("quote") or claim.text == str(row.get("value")) for row in sources)
        except (ValueError, KeyError):
            valid = False
        if valid:
            allowed_spans.append(text)
            source = sources[0]
            reply = reply.replace(text, text + f" ([source, {str(source['checked_at'])[:10]}]({source['source_url']}))", 1)
        else:
            reply = reply.replace(text, "")
            violations.append("ungrounded_world_claim")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", reply):
        matches = re.findall(rules["numeric_world_pattern"], sentence)
        if matches and not any(span in sentence for span in allowed_spans) and any(value not in student_context for value in matches):
            reply = reply.replace(sentence, "")
            violations.append("ungrounded_world_number")
    if violations:
        reply = reply.strip() + ("\n\n" if reply.strip() else "") + rules["checking_reply"]
    return reply, list(dict.fromkeys(violations))
