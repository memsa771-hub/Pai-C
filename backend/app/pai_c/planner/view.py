"""Bounded Planner input; never modifies the complete stored Truth Map."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from app.config import config

PARTS = ("said", "shown", "source", "self", "pressures.items")
MANDATORY = ("sure", "tensions", "identity_status", "decision_difficulties",
             "hypotheses", "open_questions", "coverage", "depth_mode", "engagement_style")


class PlannerInputTooLarge(ValueError):
    """Mandatory content cannot fit; keep the last good map and plan."""


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
    data["pressures"] = {"people": deepcopy(original["pressures"]["people"])}
    lists = {}
    omitted = {}
    for part in PARTS:
        rows = original["pressures"]["items"] if part == "pressures.items" else original[part]
        selected = []
        for row in rows:
            if row.get("status", "active") != "active":
                continue
            fields = ("id", "key", "value", "kind", "confidence", "level", "last_confirmed")
            entry = {key: deepcopy(row.get(key)) for key in fields}
            entry["evidence"] = row["evidence"][:200]
            if part == "source":
                entry["category"] = row["category"]
            selected.append(entry)
        lists[part] = selected
        omitted[part] = 0
        if part == "pressures.items":
            data["pressures"]["items"] = selected
        else:
            data[part] = selected
    def render():
        return "<notebook>" + _json(data) + "</notebook>\n<omitted_items>" + _json(omitted) + "</omitted_items>"
    def confirmed_at(row):
        timestamp = datetime.fromisoformat(row["last_confirmed"])
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    text = render()
    while estimated_tokens(text) > budget:
        removed = False
        for part in PARTS:
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
            raise PlannerInputTooLarge("mandatory Planner content exceeds map budget")
    ids = frozenset(row["id"] for rows in lists.values() for row in rows)
    return PlannerView(data, omitted, ids, text, estimated_tokens(text))
