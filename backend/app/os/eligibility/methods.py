"""Generic grade methods (Slice 4 spec S4-D2). Every number comes from a route's playbook; none is written here."""

import math
from collections.abc import Mapping

_EPS = 1e-9  # float noise: 4.300000000000001 is 4.3, not past it


def linear_scale(grade: float, scale_best: float, min_pass: float, target_best: float, target_worst_pass: float,
                 decimals: int, rounding: str) -> float:
    """Maps a grade from the student's scale onto a target scale by its best grade and its minimum pass:

        target_best + (target_worst_pass - target_best) * (scale_best - grade) / (scale_best - min_pass)

    With a target of 1.0 (best) and 4.0 (worst pass) this is the modified Bavarian formula. Not clamped: a grade
    below the minimum pass lands past the target's worst pass, so it reads as below any requirement."""
    span = scale_best - min_pass
    if span == 0:
        raise ValueError("the grade scale's best grade equals its minimum pass")
    x = target_best + (target_worst_pass - target_best) * (scale_best - grade) / span
    f = 10 ** decimals
    if rounding == "truncate":
        return (math.floor(x * f + _EPS) if x >= 0 else math.ceil(x * f - _EPS)) / f
    return math.floor(x * f + 0.5 + _EPS) / f  # half up, not banker's rounding


def meets(have: float, need: float, better: str) -> bool:
    """Whether `have` reaches `need` on a scale where `better` is "lower" or "higher". Equal meets."""
    return have <= need + _EPS if better == "lower" else have >= need - _EPS


def weighted_aggregate(values: Mapping[str, float], weights: Mapping[str, float],
                       totals: Mapping[str, float] | None = None) -> float:
    """The weighted sum of the named values. A value with a total is first made a percentage of it.
    A missing value raises KeyError naming it."""
    totals = totals or {}
    out = 0.0
    for key, weight in weights.items():
        if key not in values:
            raise KeyError(key)
        v = float(values[key])
        if key in totals:
            v = v / float(totals[key]) * 100
        out += weight * v
    return out
