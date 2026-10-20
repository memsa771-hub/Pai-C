"""Scoring production research against the Spike 1 answer key (Slice 2 plan Task 10, spec §9).

The matching rules are Spike 1's (backend/spikes/spike1/fields.py and score.py, design §4), copied here so the
quality gate keeps working once backend/spikes/ is deleted after the gate passes (plan Task 10 step 5).
Test code: route-specific names are allowed here (invariant 12 covers app/os only).
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KEY_PATH = Path(__file__).parent / "spike1_answer_key.yaml"
PASS_CORRECT, PASS_CONFIRMED = 0.95, 0.70
ENGLISH_KEYS = ("cefr", "ielts", "toefl_ibt", "pte", "moi_accepted")
_TESTS = {"testas": "TestAS", "gate": "GATE", "gre": "GRE", "dmat": "dMat"}


def load_key(path: Path = KEY_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["programmes"]


def _dump(value: Any) -> Any:
    return value.model_dump() if hasattr(value, "model_dump") else value


def named_tests(entries: list[str]) -> set[str]:
    """Answer-key admission tests are prose ('GRE Q160 V145 AW4.5'); keep the test names."""
    return {_TESTS[w.lower()] for e in entries for w in re.findall(r"[A-Za-z]+", e) if w.lower() in _TESTS}


def scorable(f: str, key: Any) -> bool:
    if key is None:
        return False
    if f == "english_requirement":
        return any(key.get(k) is not None for k in ENGLISH_KEYS)
    if f == "grade_requirement":
        return key.get("german_max") is not None or key.get("percent_min") is not None
    if f == "semester_contribution_eur":
        return key.get("value") is not None
    if f == "admission_test":
        return bool(named_tests(key.get("any_of", [])))
    return True


def match_key(f: str, key: Any, agent: Any) -> bool:
    a = _dump(agent)
    if f == "semester_contribution_eur":
        tolerance = 0.10 * key["value"] if key.get("approx") else 1.0
        return abs(float(a) - float(key["value"])) <= tolerance
    if f == "tuition_fee_non_eu_eur":
        return float(a) == float(key)
    if f == "english_requirement":
        return all(a.get(k) == key[k] for k in ENGLISH_KEYS if key.get(k) is not None)
    if f == "german_requirement":
        return a["level"] == key["level"]
    if f == "grade_requirement":
        return all(a.get(k) == key[k] for k in ("german_max", "percent_min") if key.get(k) is not None)
    if f == "admission_test":
        return set(a["any_of"]) - {"other"} == named_tests(key["any_of"])
    if f == "intakes":
        return set(a) == set(key)
    return a == key


@dataclass
class Score:
    scored: int = 0
    confirmed: int = 0
    correct: int = 0
    wrong: list[dict] = field(default_factory=list)
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


def score(key: dict, verdicts: dict[str, dict], fields: list[str]) -> Score:
    """`verdicts[ref][field]` has .status, .value, .reasons, .url and .quote (trust.Verdict or the like).
    Only settled key rows and fields are scored; a key value the matcher cannot check is skipped."""
    s = Score()
    for ref, row in key.items():
        if row["key_status"] != "confirmed":
            continue
        open_fields = set(row.get("open_fields", []))
        for f in fields:
            v = verdicts.get(ref, {}).get(f)
            expected = row["facts"].get(f)
            if f in open_fields or not scorable(f, expected):
                continue
            s.scored += 1
            if v is None or v.status != "confirmed":
                for r in (v.reasons if v is not None else []):
                    s.reasons[r.split(":", 1)[1] if r[:2] in ("A:", "B:", "C:") else r.split(":")[0]] += 1
                continue
            s.confirmed += 1
            if match_key(f, expected, v.value):
                s.correct += 1
            else:
                s.wrong.append({"ref": ref, "field": f, "expected": expected, "got": v.value, "url": v.url,
                                "quote": v.quote, "reasons": v.reasons})
    return s
