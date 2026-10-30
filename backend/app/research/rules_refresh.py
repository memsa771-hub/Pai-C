"""Monthly rules and calendar refresh (BETA_CONVERSATION_SPEC 3.3).

Reads each admission rule's and calendar row's own source, asks the
`researcher` model for the value the page states now with a verbatim quote,
checks the quote against the page, and writes a proposal file of diffs. It
never edits the policy files: a person reviews the proposal and applies it
with scripts/apply_refresh.py, which validates before keeping the change.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import config
from app.inference.gateway import _defaults as role_defaults, complete
from app.plugins._shared.budget import record_model_usage
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.policy.controller import POLICY_DIR, load_data
from app.plugins._shared.sources import numbers, public_https, quote_on_page, read_page, real_quote, same_site

logger = logging.getLogger(__name__)
JOB_RULES_REFRESH = "counselor.rules_refresh"


def policy() -> dict:
    return load_data("rules_refresh.json")


def proposals_dir() -> Path:
    """PAI_PROPOSALS_DIR (a host-mounted folder in Docker), else the policy folder's own."""
    return Path(config.PAI_PROPOSALS_DIR) if config.PAI_PROPOSALS_DIR else POLICY_DIR / policy()["proposals_dir"]


def _walk(node, parts: list[str], trail: list[str]):
    """(pointer parts, item) for every node the glob matches; `*` is every
    key or index, keys starting with _ are notes."""
    if not parts:
        yield trail, node
        return
    head, rest = parts[0], parts[1:]
    if isinstance(node, list):
        indexes = range(len(node)) if head == "*" else [int(head)] if head.isdigit() and int(head) < len(node) else []
        for index in indexes:
            yield from _walk(node[index], rest, [*trail, str(index)])
    elif isinstance(node, dict):
        keys = [key for key in node if not key.startswith("_")] if head == "*" else [head] if head in node else []
        for key in keys:
            yield from _walk(node[key], rest, [*trail, key])


def _first_url(value) -> str | None:
    for url in value if isinstance(value, list) else [value]:
        if isinstance(url, str) and public_https(url):
            return url
    return None


def refresh_items(files: dict[str, dict] | None = None) -> list[dict]:
    """Every value the policy says to check: {path, file, pointer, field,
    label, current, source_url}, where path is "<file>:<pointer>/<field>"."""
    items = []
    for name, targets in policy()["targets"].items():
        data = (files or {}).get(name) or load_data(name)
        for target in targets:
            for trail, node in _walk(data, target["glob"].split("/"), []):
                if not isinstance(node, dict):
                    continue
                url = _first_url(node.get(target["sources"]))
                label = node.get(target["label"])
                for field in target["fields"]:
                    if url and field in node:
                        pointer = "/".join([*trail, field])
                        items.append({"path": f"{name}:{pointer}", "file": name, "pointer": pointer, "field": field,
                                      "label": label if isinstance(label, str) else json.dumps(label, ensure_ascii=False),
                                      "current": node[field], "source_url": url})
    return items


def _parse(raw) -> list[dict]:
    try:
        values = json.loads(raw).get("values")
    except (AttributeError, TypeError, ValueError):
        return []
    return [row for row in values if isinstance(row, dict)] if isinstance(values, list) else []


def states_value(value, quote: str, rules: dict, kind: str | None = None) -> bool:
    """The quote states the proposed value in its own context: a month (kind
    "month") by its name next to a day or a year ("May 2027", "27 March"),
    so the verb "may" never counts; a percent (kind "percent") as a number
    next to "%" or "percent"; any other number as a number; text as itself.
    A list needs every element. Anything else is never stated."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, list):
        return bool(value) and all(states_value(element, quote, rules, kind) for element in value)
    if isinstance(value, (int, float)):
        if kind == "month":
            if not (isinstance(value, int) and 1 <= value <= 12):
                return False
            names = "|".join(re.escape(name) for name in rules["month_names"][value - 1])
            return bool(re.search(rf"\b\d{{1,4}}(?:st|nd|rd|th)?\s+(?:{names})\b|\b(?:{names})\.?\s+\d{{1,4}}\b",
                                  quote, re.IGNORECASE))
        text = str(int(value)) if float(value).is_integer() else str(value)
        if kind == "percent":
            found = {raw.replace(",", "") for raw in re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent\b|per cent\b)",
                                                                  quote, re.IGNORECASE)}
            return text in {number[:-2] if number.endswith(".0") else number for number in found}
        return text in numbers(quote)
    words = " " + re.sub(r"[^a-z0-9]+", " ", quote.lower()) + " "
    return isinstance(value, str) and f" {' '.join(re.findall(r'[a-z0-9]+', value.lower()))} " in words


def _verified(row: dict, item: dict, page: dict, rules: dict) -> bool:
    """A real passage on the page that states the new value."""
    quote = row.get("quote")
    if not isinstance(quote, str) or not quote_on_page(quote, page["text"]) or not real_quote(quote, rules["quote_rules"]):
        return False
    kind = "month" if "month" in item["field"] else "percent" if "percent" in item["field"] else None
    return states_value(row.get("value"), quote, rules, kind)


async def run_refresh(*, max_calls: int | None = None, out_dir: Path | None = None,
                      today: datetime | None = None, files: dict[str, dict] | None = None) -> Path:
    """One refresh: one page read and one model call per source URL while the
    call budget lasts, then the proposal file. Returns the file's path."""
    rules = policy()
    today = today or datetime.now(timezone.utc)
    calls = config.PAI_RULES_REFRESH_MAX_CALLS if max_calls is None else max_calls
    by_url: dict[str, list[dict]] = {}
    for item in refresh_items(files):
        by_url.setdefault(item["source_url"], []).append(item)
    diffs, unread, checked_items, skipped = [], [], 0, 0
    # A budget smaller than the sources reads a different slice each month,
    # so every source is read within a few runs.
    urls = list(by_url)
    start = ((today.year * 12 + today.month) * max(1, calls // 2)) % len(urls) if urls else 0
    for url in urls[start:] + urls[:start]:
        items = by_url[url]
        if calls < 2:
            skipped += len(items)
            continue
        calls -= 1
        page = await read_page(url, rules["page_chars"])
        # Only the rule's own site counts: a redirect elsewhere is unread.
        if page is None or not same_site(page["url"], url):
            logger.warning("rules_refresh_unread url=%s reason=page", url)
            unread.append(url)
            continue
        calls -= 1
        try:
            raw = await complete(role="researcher", phase="rules_refresh", system_prompt=load_prompt("rules_refresh"),
                messages=[{"role": "user", "content": json.dumps({
                    "source_url": url, "page": page["text"],
                    "items": [{"path": item["path"], "label": item["label"], "field": item["field"],
                               "current": item["current"]} for item in items]}, ensure_ascii=False)}],
                response_format={"type": "json_object"}, max_tokens=role_defaults("researcher").get("max_tokens"),
                usage_callback=record_model_usage)
        except Exception as exc:  # noqa: BLE001  one source's failure (output limit, 400, 5xx, timeout) is that source unread
            logger.warning("rules_refresh_unread url=%s reason=model error_type=%s error=%s",
                           url, type(exc).__name__, str(exc)[:200])
            unread.append(url)
            continue
        checked_items += len(items)
        asked = {item["path"]: item for item in items}
        for row in _parse(raw):
            item = asked.pop(str(row.get("path")), None)
            if item is None or row.get("value") is None or row.get("value") == item["current"]:
                continue
            if not _verified(row, item, page, rules):
                continue
            confidence = row.get("confidence") if row.get("confidence") in rules["confidence_levels"] else rules["confidence_levels"][-1]
            diffs.append({"path": item["path"], "old": item["current"], "new": row["value"], "quote": row["quote"],
                          "source_url": item["source_url"], "confidence": confidence})
    proposal = {"created_at": today.isoformat(), "applied": False, "diffs": diffs,
                "checked_items": checked_items, "skipped_for_budget": skipped, "unread_sources": unread}
    folder = out_dir or proposals_dir()
    folder.mkdir(parents=True, exist_ok=True)
    # A second run on the same day never overwrites a proposal under review.
    target, n = folder / f"{today.date().isoformat()}.json", 1
    while target.exists():
        n += 1
        target = folder / f"{today.date().isoformat()}-{n}.json"
    target.write_text(json.dumps(proposal, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("rules_refresh_proposal path=%s diffs=%d checked=%d unread=%d skipped=%d",
                target, len(diffs), checked_items, len(unread), skipped)
    return target


async def rules_refresh_job(job, db) -> dict:
    from app.inference import usage
    # Gated on its own cap entry and on the role it calls.
    if not usage.role_allowed("rules_refresh") or not usage.role_allowed("researcher"):
        # Monthly model cap (research_paused): a quiet skip, logged once a day.
        return {"status": "cap_paused"}
    db.rollback()
    target = await run_refresh()
    proposal = json.loads(target.read_text(encoding="utf-8"))
    return {"status": "proposed", "file": target.name, "diffs": len(proposal["diffs"])}

