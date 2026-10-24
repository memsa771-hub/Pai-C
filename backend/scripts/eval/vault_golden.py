"""Vault golden set: cases, a schema-neutral view of the Vault, and scoring.

A case states what is true about a synthetic student ("FSc Pre-Engineering,
Lahore board, 85%"), not how the Vault stores it. `facets_from_profile` maps
whatever the Vault holds today onto the same facet vocabulary, so the cases
stay valid while the schema changes; only that adapter follows the schema.
"""
import json
import re
import unicodedata
from pathlib import Path

CASES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "vault_golden"
LANGUAGES = ("en", "roman_ur", "ur", "mixed")

# Core facets carry eligibility and matching; story facets carry understanding.
FACETS = {
    "name": "core", "dob": "core", "city": "core", "status": "core",
    "education": "core", "subject_mark": "core", "test": "core",
    "budget": "core", "mobility": "core", "scholarship": "core",
    "family_member": "core", "domicile": "core", "quota": "core",
    "interest": "story", "experience": "story", "skill": "story", "strength": "story",
    "value": "story", "pressure": "story", "goal": "story", "option": "story",
    "myth": "story", "certainty": "story",
}

_EXPERIENCE_KINDS = ("activity", "project", "achievement", "work_experience",
                     "exploration_experience", "research")
_SKILL_KINDS = ("skill", "language_proficiency", "certification")
# Words that only occur in untranslated Roman Urdu; English values never hold them.
_ROMAN_URDU = frozenset({
    "hai", "hain", "nahi", "nahin", "kiya", "tha", "thi", "hoon", "mera", "meri",
    "mujhe", "bohat", "bahut", "raha", "rahi", "abbu", "ammi", "acha", "achi",
    "karna", "karni", "wala", "wali", "lekin", "kyunke", "sakta", "sakti",
})
_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def load_cases(directory: Path = CASES) -> list[dict]:
    cases = []
    for path in sorted(directory.glob("*.json")):
        cases.extend(json.loads(path.read_text(encoding="utf-8")))
    for case in cases:
        validate_case(case)
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("golden case ids must be unique")
    return cases


def validate_case(case: dict) -> None:
    def fail(reason):
        raise ValueError(f"golden case {case.get('id')!r}: {reason}")

    if not isinstance(case.get("id"), str) or not case["id"]:
        fail("id is required")
    if case.get("language") not in LANGUAGES:
        fail("language must be one of " + ", ".join(LANGUAGES))
    if case.get("synthetic") is not True:
        fail("synthetic must be true until real, consented samples exist")
    turns = case.get("turns")
    if not isinstance(turns, list) or not turns or not all(isinstance(t, str) and t.strip() for t in turns):
        fail("turns must be a non-empty list of student messages")
    for section in ("expected", "must_not"):
        for item in case.get(section, []):
            if item.get("facet") not in FACETS:
                fail(f"unknown facet {item.get('facet')!r} in {section}")
            if not isinstance(item.get("match"), dict):
                fail(f"{section} items need a match object")
            for spec in item["match"].values():
                _check_spec(spec, fail)
    if not case.get("expected"):
        fail("expected must list at least one facet")
    for item in case.get("must_not", []):
        if not item.get("why"):
            fail("every must_not item needs a why")


def _check_spec(spec, fail) -> None:
    if isinstance(spec, str):
        return
    if isinstance(spec, list) and spec and all(isinstance(s, str) for s in spec):
        return
    if isinstance(spec, dict) and (
        ("all" in spec and all(isinstance(s, str) for s in spec["all"]))
        or isinstance(spec.get("num"), (int, float))
        or (isinstance(spec.get("between"), list) and len(spec["between"]) == 2)
        or (isinstance(spec.get("one_of"), list) and spec["one_of"])
    ):
        return
    fail(f"unsupported match spec {spec!r}")


def norm(value) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group()) if match else None


def spec_matches(spec, observed) -> bool:
    if observed is None:
        return False
    if isinstance(spec, str):
        return norm(spec) in norm(observed)
    if isinstance(spec, list):
        return any(norm(item) in norm(observed) for item in spec)
    if "all" in spec:
        return all(norm(item) in norm(observed) for item in spec["all"])
    number = _number(observed)
    if number is None:
        return False
    tolerance = float(spec.get("tol", 0.01))
    if "num" in spec:
        return abs(number - spec["num"]) <= tolerance
    if "between" in spec:
        low, high = spec["between"]
        return low - tolerance <= number <= high + tolerance
    return any(abs(number - item) <= tolerance for item in spec["one_of"])


def facet_matches(match: dict, facet: dict) -> bool:
    return all(spec_matches(spec, facet.get(field)) for field, spec in match.items())


def _text(*values) -> str:
    parts = []
    for value in values:
        if isinstance(value, dict):
            parts.append(_text(*value.values()))
        elif isinstance(value, (list, tuple)):
            parts.append(_text(*value))
        elif value is not None and value != "":
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _facet(kind: str, /, **fields) -> dict:
    fields = {key: value for key, value in fields.items() if value not in (None, "", [])}
    return {"facet": kind, **fields, "text": _text(*fields.values())}


def _percent(result: dict):
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("percentage"), (int, float)):
        return float(result["percentage"])
    obtained, total = result.get("marks_obtained"), result.get("marks_total")
    if isinstance(obtained, (int, float)) and isinstance(total, (int, float)) and total:
        return round(obtained / total * 100, 2)
    gpa, scale = result.get("gpa"), result.get("gpa_scale")
    if isinstance(gpa, (int, float)) and isinstance(scale, (int, float)) and scale:
        return round(gpa / scale * 100, 2)
    return None


def facets_from_profile(profile: dict) -> list[dict]:
    """Map today's Vault (facts + typed records) onto the facet vocabulary.

    Only the Vault counts. The Truth Map notebook is deliberately excluded:
    the plan's target is that everything about the student lives in the Vault.
    """
    facts = profile.get("facts") or {}
    records = profile.get("records") or {}
    out = []
    for key in ("identity.preferred_name", "identity.full_name"):
        if facts.get(key):
            out.append(_facet("name", value=facts[key]))
    if facts.get("identity.date_of_birth"):
        out.append(_facet("dob", value=facts["identity.date_of_birth"]))
    if facts.get("location.current_city"):
        out.append(_facet("city", value=facts["location.current_city"]))
    if facts.get("identity.current_status"):
        out.append(_facet("status", value=facts["identity.current_status"]))
    budget = facts.get("finance.budget")
    if isinstance(budget, dict):
        out.append(_facet("budget", amount=budget.get("amount"), currency=budget.get("currency"),
                          period=budget.get("period")))
    if facts.get("finance.scholarship_interest") is not None or facts.get("finance.funding_status"):
        out.append(_facet("scholarship", value=_text(facts.get("finance.scholarship_interest"),
                                                     facts.get("finance.funding_status"))))
    if facts.get("mobility.relocation_willingness"):
        out.append(_facet("mobility", value=facts["mobility.relocation_willingness"]))
    for limit in facts.get("preferences.location_limits") or []:
        out.append(_facet("mobility", value=limit))
    if facts.get("career.primary_interest"):
        out.append(_facet("interest", value=facts["career.primary_interest"]))
    for country in facts.get("preferences.target_countries") or []:
        out.append(_facet("option", value=country))

    for row in records.get("education", []):
        details = row.get("details") or {}
        out.append(_facet(
            "education", level=_text(row.get("canonical_level"), row.get("qualification_name")),
            group=_text(row.get("field_of_study"), details.get("specialization"), details.get("major")),
            board=details.get("awarding_body"), institution=row.get("institution_name"),
            year=_text(row.get("graduation_year"), row.get("end_date")),
            status=row.get("academic_status"), marks=_percent(row.get("result")),
            result=row.get("result")))
    for row in records.get("course", []):
        out.append(_facet("subject_mark", subject=_text(row.get("name"), row.get("normalized_name")),
                          score=row.get("score"), grade=row.get("grade")))
    for row in records.get("test_attempt", []):
        out.append(_facet("test", name=_text(row.get("test_type"), row.get("original_name")),
                          score=row.get("overall_score"), date=row.get("test_date")))
    for row in records.get("goal", []):
        out.append(_facet("goal", owner="student", title=row.get("title"),
                          commitment=row.get("commitment"), details=row.get("details")))
    for kind in _EXPERIENCE_KINDS:
        for row in records.get(kind, []):
            out.append(_facet("experience", kind=kind,
                              value=_text({k: v for k, v in row.items() if k not in ("id", "verification_status")})))
    for kind in _SKILL_KINDS:
        for row in records.get(kind, []):
            out.append(_facet("skill", value=_text(row.get("name"), row.get("language"), row.get("title"),
                                                   row.get("proficiency"))))
    for row in records.get("external_influence", []):
        out.append(_facet("family_member", who=_text(row.get("influencer_type"), row.get("source_label")),
                          wish=row.get("suggested_direction")))
    return out


def not_english(facet: dict) -> bool:
    """True when a stored value is still in Urdu script or untranslated Roman Urdu."""
    text = facet.get("text", "")
    if _ARABIC_SCRIPT.search(text):
        return True
    return bool(set(norm(text).split()) & _ROMAN_URDU)


def score_case(case: dict, facets: list[dict]) -> dict:
    expected = []
    used = set()
    for item in case["expected"]:
        hit = next((i for i, facet in enumerate(facets)
                    if facet["facet"] == item["facet"] and facet_matches(item["match"], facet)), None)
        if hit is not None:
            used.add(hit)
        expected.append({"facet": item["facet"], "tier": FACETS[item["facet"]],
                         "match": item["match"], "found": hit is not None})
    violations = [{"facet": item["facet"], "why": item["why"]}
                  for item in case.get("must_not", [])
                  if any(f["facet"] == item["facet"] and facet_matches(item["match"], f) for f in facets)]
    return {
        "id": case["id"], "language": case["language"], "expected": expected,
        "must_not_violations": violations,
        "not_english": [f["text"] for f in facets if not_english(f)],
        "extra": [f["facet"] + ": " + f["text"] for i, f in enumerate(facets) if i not in used],
    }


def summarize(results: list[dict]) -> dict:
    """Recall by tier, facet and language, plus the hard-failure counts."""
    def recall(rows):
        found = sum(row["found"] for row in rows)
        return {"found": found, "expected": len(rows),
                "recall": round(found / len(rows), 3) if rows else None}

    rows = [dict(row, language=result["language"]) for result in results for row in result["expected"]]
    return {
        "cases": len(results),
        "overall": recall(rows),
        "by_tier": {tier: recall([r for r in rows if r["tier"] == tier]) for tier in ("core", "story")},
        "by_facet": {facet: recall([r for r in rows if r["facet"] == facet])
                     for facet in FACETS if any(r["facet"] == facet for r in rows)},
        "by_language": {lang: recall([r for r in rows if r["language"] == lang])
                        for lang in LANGUAGES if any(r["language"] == lang for r in rows)},
        "must_not_violations": sum(len(r["must_not_violations"]) for r in results),
        "not_english_values": sum(len(r["not_english"]) for r in results),
    }
