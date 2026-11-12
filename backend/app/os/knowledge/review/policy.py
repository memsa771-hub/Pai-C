"""The review queue's policy file (knowledge/review/review_policy.yaml): which reviewers count, the steps, the
evidence limits. Loaded once and checked; a bad file stops the load."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from app.os import models

POLICY_FILE = Path(__file__).with_name("review_policy.yaml")


@dataclass(frozen=True)
class ReviewPolicy:
    counting_kinds: tuple[str, ...]
    min_persons: int
    steps_high_stakes: int
    steps_other: int
    compare_with_original: tuple[str, ...]
    evidence_max_bytes: int
    evidence_types: tuple[str, ...]
    collect_needs_evidence: bool
    sync_high_stakes_only: bool
    snapshot_max_chars: int


def parse(data: dict) -> ReviewPolicy:
    kinds = tuple(data["counting_kinds"])
    if not kinds or set(kinds) - set(models.REVIEWER_KINDS):
        raise ValueError(f"counting_kinds must be a non-empty subset of {models.REVIEWER_KINDS}")
    if data["min_persons"] < 0 or (data["min_persons"] > 0 and "person" not in kinds):
        raise ValueError("min_persons needs 'person' in counting_kinds")
    if (data["steps_high_stakes"], data["steps_other"]) not in ((2, 1), (2, 2), (1, 1)):
        raise ValueError("steps must be 2/1, 2/2 or 1/1")
    ev = data["evidence"]
    return ReviewPolicy(kinds, int(data["min_persons"]), data["steps_high_stakes"], data["steps_other"],
                        tuple(data["compare_with_original"]), int(ev["max_bytes"]), tuple(ev["content_types"]),
                        bool(ev["required_for_collect"]), bool(data["sync"]["high_stakes_only"]),
                        int(data["snapshot_max_chars"]))


@cache
def load_policy(path: Path = POLICY_FILE) -> ReviewPolicy:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
