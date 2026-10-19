"""Scoring against the answer key (design §4) and the pass bar (parent §5, row 1)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from spikes.spike1.fields import FIELDS, match_key, scorable
from spikes.spike1.trust import Verdict

PASS_CORRECT = 0.95
PASS_CONFIRMED = 0.70


@dataclass
class Score:
    scored: int = 0
    confirmed: int = 0
    correct: int = 0
    wrong: list[dict[str, Any]] = field(default_factory=list)
    extras: list[dict[str, Any]] = field(default_factory=list)  # confirmed where the key is null: for review
    unsettled: list[dict[str, Any]] = field(default_factory=list)  # key rows/fields not settled: for review
    per_field: dict[str, Counter] = field(default_factory=dict)
    reasons: Counter = field(default_factory=Counter)

    @property
    def correct_rate(self) -> float:
        return self.correct / self.confirmed if self.confirmed else 0.0

    @property
    def confirmed_rate(self) -> float:
        return self.confirmed / self.scored if self.scored else 0.0

    def verdict(self) -> tuple[bool, list[str]]:
        fails = []
        if self.correct_rate < PASS_CORRECT:
            fails.append(f"correct_rate {self.correct_rate:.3f} < {PASS_CORRECT}")
        if self.confirmed_rate < PASS_CONFIRMED:
            fails.append(f"confirmed_rate {self.confirmed_rate:.3f} < {PASS_CONFIRMED}")
        if not self.scored:
            fails.append("nothing scored")
        return not fails, fails


def score(key: dict, verdicts: dict[str, dict[str, Verdict]]) -> Score:
    s = Score(per_field={f: Counter() for f in FIELDS})
    for ref, row in key.items():
        got = verdicts.get(ref, {})
        settled = row["key_status"] == "confirmed"
        open_fields = set(row.get("open_fields", []))
        for f in FIELDS:
            v = got.get(f) or Verdict("not_found")
            expected = row["facts"][f]
            for r in v.reasons:
                r = r[2:] if r[:2] in ("A:", "B:") else r
                s.reasons[r.split(":")[0]] += 1
            item = {"ref": ref, "field": f, "expected": expected, "got": v.value, "status": v.status,
                    "url": v.url, "quote": v.quote, "reasons": v.reasons}
            if not settled or f in open_fields:
                if v.status != "not_found":
                    s.unsettled.append(item)
                continue
            if not scorable(f, expected):
                if v.status == "confirmed":
                    s.extras.append(item)
                continue
            s.scored += 1
            s.per_field[f]["scored"] += 1
            if v.status != "confirmed":
                continue
            s.confirmed += 1
            s.per_field[f]["confirmed"] += 1
            if match_key(f, expected, v.value):
                s.correct += 1
                s.per_field[f]["correct"] += 1
            else:
                s.wrong.append(item)
    return s
