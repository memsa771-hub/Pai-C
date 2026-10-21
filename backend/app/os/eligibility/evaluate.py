"""One programme's eligibility card for one student, computed on read (Slice 4 spec S4-D3, S4-D5).

Pure: the route's rules (its playbook), the programme's facts (Slice 2) and the student's confirmed profile values
(Slice 3, keys "<doc_type>.<field>") go in, a card comes out. Nothing is stored and nothing is blocked: a line says
`likely_meets`, `likely_below`, `needs_input` (a value the student has not confirmed yet) or `unknown` (a fact
research has not found). Every number and name comes from the rules; the code knows only the generic kinds.
"""

from dataclasses import dataclass, field
from typing import Any

from app.os.eligibility.methods import linear_scale, meets, weighted_aggregate
from app.os.eligibility.rules import EligibilityRules, GradeCheck, LanguageCheck, TestCheck
from app.os.knowledge.port import Fact

ORDER = ("likely_below", "needs_input", "unknown", "likely_meets")  # worst first: the verdict is the worst line
# why a value is not usable, most telling first
_REASONS = ("open_finding", "not_a_number", "missing_value")


@dataclass(frozen=True)
class FactRef:
    field: str
    url: str
    status: str


@dataclass(frozen=True)
class Line:
    check: str  # "grade", "language:<language>", "test"
    status: str
    have: Any = None
    need: Any = None
    provisional: bool = False  # a route default stands in for the student's own value (S4-D6)
    needs: list[str] = field(default_factory=list)  # document types whose confirmation would fill this line
    reason: str | None = None  # open_finding | not_a_number | missing_value | missing_fact | no_proof_type
    sources: list[FactRef] = field(default_factory=list)


@dataclass(frozen=True)
class Card:
    programme_ref: str
    verdict: str
    lines: list[Line]


def _doc_type(key: str) -> str:
    return key.split(".", 1)[0]


def _ref(name: str, f: Fact) -> FactRef:
    return FactRef(name, f.url, f.status)


def _part(f: Fact | None, part: str | None) -> Any:
    if f is None or f.value is None:
        return None
    if part is None:
        return f.value
    return f.value.get(part) if isinstance(f.value, dict) else None


class _Values:
    """The student's values, with why one is unusable."""

    def __init__(self, profile: dict, held: frozenset[str]) -> None:
        self.profile, self.held = profile, held

    def number(self, key: str) -> tuple[float | None, str | None]:
        if key in self.held:
            return None, "open_finding"
        v = self.profile.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            return None, "missing_value"
        try:
            return float(v), None
        except (TypeError, ValueError):
            return None, "not_a_number"


def _worst_reason(reasons: list[str]) -> str:
    return min(reasons, key=_REASONS.index) if reasons else "missing_value"


def _grade(rules: EligibilityRules, facts: dict[str, Fact], vals: _Values) -> Line | None:
    if not rules.grade:
        return None
    for check in rules.grade:  # the first check whose requirement is stated decides
        need = _part(facts.get(check.requirement), check.part)
        if need is not None:
            return _grade_line(rules, check, float(need), [_ref(check.requirement, facts[check.requirement])], vals)
    seen = [_ref(c.requirement, facts[c.requirement]) for c in rules.grade if c.requirement in facts]
    return Line("grade", "unknown", reason="missing_fact", sources=list(dict.fromkeys(seen)))


def _grade_line(rules: EligibilityRules, check: GradeCheck, need: float, sources: list[FactRef],
                vals: _Values) -> Line:
    if check.method == "weighted_aggregate":
        keys = list(check.weights) + [k for k in check.totals.values() if k not in check.weights]
        got, reasons = {}, []
        for k in keys:
            v, why = vals.number(k)
            if why:
                reasons.append(why)
            else:
                got[k] = v
        if reasons:
            missing = [k for k in keys if k not in got]
            return Line("grade", "needs_input", need=need, needs=list(dict.fromkeys(map(_doc_type, missing))),
                        reason=_worst_reason(reasons), sources=sources)
        totals = {k: got[t] for k, t in check.totals.items()}
        have = round(weighted_aggregate(got, check.weights, totals), 2)
        return Line("grade", "likely_meets" if meets(have, need, check.better) else "likely_below", have, need,
                    sources=sources)

    reasons = []
    for name in check.scales:  # the first scale the student has a usable value on
        scale = rules.grade_scales[name]
        value, why = vals.number(scale.value)
        if why:
            reasons.append(why)
            continue
        provisional, needs = False, []
        if check.method == "linear_scale":
            min_pass = _own_min_pass(scale, vals)
            if min_pass is None:  # the route's default stands in, labelled, until the student's letter (S4-D6)
                min_pass, provisional = scale.provisional_min_pass, True
                needs = [_doc_type(scale.min_pass)] if scale.min_pass else []
            t = check.target
            have = linear_scale(value, scale.best, min_pass, t.best, t.worst_pass, t.decimals, t.rounding)
        else:
            have = value
        return Line("grade", "likely_meets" if meets(have, need, check.better) else "likely_below", have, need,
                    provisional=provisional, needs=needs, sources=sources)
    docs = [_doc_type(rules.grade_scales[n].value) for n in check.scales]
    return Line("grade", "needs_input", need=need, needs=list(dict.fromkeys(docs)), reason=_worst_reason(reasons),
                sources=sources)


def _own_min_pass(scale, vals: _Values) -> float | None:
    """The student's confirmed minimum pass for this scale: only from a letter about a scale with the same best
    grade (a percentage letter does not set a CGPA scale's minimum), and never under an open finding."""
    if not scale.min_pass:
        return None
    if scale.min_pass_scale:
        best, why = vals.number(scale.min_pass_scale)
        if why or abs(best - scale.best) > 1e-9:
            return None
    value, why = vals.number(scale.min_pass)
    return None if why else value


def _language(check: LanguageCheck, facts: dict[str, Fact], vals: _Values) -> Line:
    name = f"language:{check.language}"
    f = facts.get(check.requirement)
    if f is None or f.value is None:
        return Line(name, "unknown", reason="missing_fact", sources=[_ref(check.requirement, f)] if f else [])
    sources = [_ref(check.requirement, f)]
    req = f.value if isinstance(f.value, dict) else {}
    level = req.get(check.level_key) if check.level_key else None
    required = {k: req[k] for k in check.scores if req.get(k) is not None}
    if not required:
        if level is None or str(level).strip().casefold() in {v.casefold() for v in check.none_values}:
            return Line(name, "likely_meets", need=level, sources=sources)
        return Line(name, "needs_input", need=level, reason="no_proof_type", sources=sources)
    reasons, best = [], None
    for score_key, need in required.items():  # any one accepted test with a high-enough score is enough
        have, why = vals.number(check.scores[score_key])
        if why:
            reasons.append(why)
            continue
        line = Line(name, "likely_meets" if meets(have, float(need), "higher") else "likely_below", have,
                    float(need), sources=sources)
        if best is None or line.status == "likely_meets":
            best = line
    if best is not None:
        return best
    docs = [_doc_type(check.scores[k]) for k in required]
    return Line(name, "needs_input", need=next(iter(required.values())), needs=list(dict.fromkeys(docs)),
                reason=_worst_reason(reasons), sources=sources)


def _test(check: TestCheck, facts: dict[str, Fact]) -> Line:
    if check.requirement not in facts:
        return Line("test", "unknown", reason="missing_fact")
    f = facts[check.requirement]
    sources = [_ref(check.requirement, f)]
    tests = f.value.get(check.list_key) if isinstance(f.value, dict) else f.value
    if not tests:  # the pages say no test is needed
        return Line("test", "likely_meets", sources=sources)
    return Line("test", "needs_input", need=list(tests), reason="no_proof_type", sources=sources)


def evaluate(rules: EligibilityRules, programme_ref: str, facts: dict[str, Fact], profile: dict[str, Any],
             held: frozenset[str] = frozenset()) -> Card:
    """`facts` maps a research field to its fact for this programme; `profile` maps a profile key to its confirmed
    value; `held` names the profile keys under an open Slice 3 finding (never used until the student resolves it)."""
    vals = _Values(profile, held)
    lines = [ln for ln in [_grade(rules, facts, vals)] if ln is not None]
    lines += [_language(lc, facts, vals) for lc in rules.language]
    if rules.test is not None:
        lines.append(_test(rules.test, facts))
    verdict = min((ln.status for ln in lines), key=ORDER.index) if lines else "unknown"
    return Card(programme_ref, verdict, lines)
