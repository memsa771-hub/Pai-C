# -*- coding: utf-8 -*-
"""How complete the Vault is: the areas PAI knows and the ones it still asks.

A view over `coverage_areas` (pai_c/understanding/areas.json), never a second
count. An area is known when it is covered and not stale; labels, question copy
keys and the asking order come from pai_c/policy/areas_policy.json. The
counselor's next question reads `unknown_areas` from here, and the Vault page
and the Mirror read `build`, so there is one list of what is still unknown.
"""


def _policy() -> dict:
    from app.pai_c.policy.controller import load_data
    return load_data("areas_policy.json")


def _known(row: dict) -> bool:
    return bool(row.get("covered")) and not row.get("stale")


def unknown_areas(coverage: dict, policy: dict | None = None) -> list[str]:
    """Areas not known, in asking order. An area missing from `coverage` is
    unknown; one outside the priority list goes last."""
    policy = policy if policy is not None else _policy()
    order = policy["priority"]
    areas = [*order, *(area for area in coverage if area not in order)]
    return [area for area in areas if not _known(coverage.get(area, {}))]


def completeness_from(coverage: dict, policy: dict | None = None) -> dict:
    policy = policy if policy is not None else _policy()
    labels, questions, order = policy["labels"], policy["questions"], policy["priority"]
    areas = [{"key": key, "label": labels.get(key, key), "covered": bool(row.get("covered")),
              "evidence": row.get("evidence"), "stale": bool(row.get("stale")),
              "item_count": row.get("item_count", 0), "min_items": row.get("min_items", 1),
              "question_key": questions.get(key)} for key, row in coverage.items()]
    unknowns = [{"area": area, "label": labels.get(area, area), "question_key": questions.get(area),
                 "priority": order.index(area) + 1 if area in order else len(order) + 1}
                for area in unknown_areas(coverage, policy) if area in coverage]
    return {"known": sum(_known(row) for row in coverage.values()), "total": len(coverage),
            "areas": areas, "unknowns": unknowns}


class VaultCompleteness:
    def __init__(self, db):
        self.db = db

    def build(self, workspace_id: str) -> dict:
        from app.pai_c.memory import MemoryService
        return completeness_from(MemoryService(self.db).coverage_areas(workspace_id))
