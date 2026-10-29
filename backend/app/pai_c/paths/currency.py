"""Whether path research is current (FOUR_FEATURES_SPEC 2.3, fix round 1).

A finished explanation or program search is never thrown away. It is current
while the path-relevant part of the Vault (`vault_trigger_types` in
path_analyzer.json) is unchanged; otherwise it is shown as stale and a new
request re-runs it.
"""

from app.pai_c.memory import relevance_version
from app.pai_c.policy.controller import load_data


def trigger_types() -> list[str]:
    return load_data("path_analyzer.json")["vault_trigger_types"]


def current_relevance(db, workspace_id: str) -> str:
    return relevance_version(db, workspace_id, trigger_types())


def is_stale(run, current: str) -> bool:
    """A run from before relevance keys (it carries no `relevance_version`)
    counts as stale."""
    return (run.constraints or {}).get("relevance_version") != current
