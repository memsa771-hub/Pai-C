"""Bounded Planner input; never modifies the complete stored Truth Map."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
from app.config import config

from app.pai_c.understanding.data import load_policy, at_path, set_path

PARTS = tuple(load_policy()["item_paths"])
MANDATORY = ("sure", "tensions", "identity_status", "decision_difficulties",
             "hypotheses", "open_questions", "coverage", "depth_mode", "engagement_style")


@dataclass(frozen=True)
class PlannerView:
    data: dict
    omitted: dict
    ids: frozenset[str]
    text: str
    tokens: int


def build_planner_view(notebook, budget=None):
    # Lazy import avoids context -> memory -> Planner dependency cycles.
    from app.pai_c.deep.context import estimated_tokens, _json
    budget = config.PAI_PLANNER_MAP_CONTEXT_TOKENS if budget is None else budget
    original = notebook.model_dump(mode="json")
    data = {key: deepcopy(original[key]) for key in MANDATORY}
    data["private_notes"] = original["private_notes"][:1000]
    parts = (*load_policy()["item_paths"], load_policy()["person_path"])
    lists = {}
    omitted = {}
    for part in parts:
        rows = at_path(original, part)
        selected = []
        for row in rows:
            if row.get("status", "active") != "active":
                continue
            fields = ("id", "key", "value", "kind", "confidence", "level", "capability_status", "last_confirmed")
            if part == load_policy()["person_path"]:
                fields = tuple(key for key in row if key != "evidence")
            entry = {key: deepcopy(row.get(key)) for key in fields}
            entry["evidence"] = row["evidence"][:200]
            if part == "source":
                entry["category"] = row["category"]
            selected.append(entry)
        lists[part] = selected
        omitted[part] = 0
        set_path(data, part, selected)
    def render():
        return "<notebook>" + _json(data) + "</notebook>\n<omitted_items>" + _json(omitted) + "</omitted_items>"
    def confirmed_at(row):
        timestamp = datetime.fromisoformat(row["last_confirmed"])
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    text = render()
    while estimated_tokens(text) > budget:
        removed = False
        for part in parts:
            rows = lists[part]
            if len(rows) <= 1:
                continue
            # Each part loses its oldest confirmed item in turn; newest survive.
            oldest = min(range(len(rows)), key=lambda index: confirmed_at(rows[index]))
            rows.pop(oldest)
            omitted[part] += 1
            removed = True
            text = render()
            if estimated_tokens(text) <= budget:
                break
        if not removed:
            break
    if estimated_tokens(text) > budget:
        data["hypotheses"] = [row for row in data["hypotheses"] if row["status"] != "rejected"]
        text = render()
    for field, limit in (("hypotheses", 8), ("tensions", 6), ("decision_difficulties", 6)):
        if estimated_tokens(text) > budget:
            # Founder decision: newest means last in the stored list order.
            data[field] = data[field][-limit:]
            text = render()
    if estimated_tokens(text) > budget:
        data["open_questions"] = data["open_questions"][:3]
        text = render()
    if estimated_tokens(text) > budget:
        data["private_notes"] = data["private_notes"][:500]
        text = render()
    if estimated_tokens(text) > budget:
        logger.warning("planner_input_over_budget tokens=%d", estimated_tokens(text))
    ids = frozenset(row["id"] for rows in lists.values() for row in rows)
    return PlannerView(data, omitted, ids, text, estimated_tokens(text))
