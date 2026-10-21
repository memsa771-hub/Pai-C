"""Slice 4 Task 2: generic grade methods (spec S4-D2). No route's numbers live here; the tests pass them in."""

import pytest

from app.os.eligibility.methods import linear_scale, meets, weighted_aggregate

GERMAN = {"target_best": 1.0, "target_worst_pass": 4.0, "decimals": 1, "rounding": "truncate"}


def test_linear_scale_german_example():
    # the modified Bavarian formula: 1 + 3 * (4.0 - 3.0) / (4.0 - 2.0)
    assert linear_scale(3.0, scale_best=4.0, min_pass=2.0, **GERMAN) == 2.5


def test_linear_scale_best_and_min():
    assert linear_scale(4.0, scale_best=4.0, min_pass=2.0, **GERMAN) == 1.0
    assert linear_scale(2.0, scale_best=4.0, min_pass=2.0, **GERMAN) == 4.0


def test_linear_scale_truncate_vs_round():
    args = {"scale_best": 4.0, "min_pass": 2.2, "target_best": 1.0, "target_worst_pass": 4.0, "decimals": 1}
    assert linear_scale(3.0, rounding="truncate", **args) == 2.6  # 2.666...
    assert linear_scale(3.0, rounding="round", **args) == 2.7


def test_linear_scale_on_a_percentage():
    assert linear_scale(76.0, scale_best=100, min_pass=33, **GERMAN) == 2.0  # 1 + 3 * 24 / 67 = 2.07 -> 2.0


def test_linear_scale_higher_is_better_target():
    # a target scale where higher is better (e.g. a 4.0 GPA): best 4.0, worst pass 1.0
    assert linear_scale(80.0, scale_best=100, min_pass=40, target_best=4.0, target_worst_pass=1.0, decimals=2,
                        rounding="round") == 3.0  # 4 - 3 * 20 / 60


def test_below_min_pass_not_clamped():
    assert linear_scale(1.8, scale_best=4.0, min_pass=2.0, **GERMAN) == 4.3


def test_zero_span_scale_refused():
    with pytest.raises(ValueError, match="scale"):
        linear_scale(3.0, scale_best=2.0, min_pass=2.0, **GERMAN)


def test_meets_both_directions():
    assert meets(2.5, 2.5, "lower") and meets(2.4, 2.5, "lower") and not meets(2.6, 2.5, "lower")
    assert meets(70, 70, "higher") and meets(71, 70, "higher") and not meets(69.9, 70, "higher")


def test_weighted_aggregate():
    values = {"hssc.marks": 990, "test.score": 80}
    totals = {"hssc.marks": 1100}
    # 0.5 * 90% + 0.5 * 80 = 85.0
    assert weighted_aggregate(values, {"hssc.marks": 0.5, "test.score": 0.5}, totals) == pytest.approx(85.0)


def test_weighted_aggregate_missing_value_refused():
    with pytest.raises(KeyError, match="test.score"):
        weighted_aggregate({"hssc.marks": 990}, {"hssc.marks": 0.5, "test.score": 0.5}, {"hssc.marks": 1100})
