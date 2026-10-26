from app.pai_c.paths.fields import known_groups, study_fields
from app.pai_c.policy.controller import load_data
from app.pai_c.roadmap.rules import ibcc_percent, rule_for

CONFIDENCE = {"official", "secondary", "uncertain"}


def _rules():
    return load_data("admission_rules.json")["rules"]


def test_rule_targets_exist():
    fields = study_fields()
    families = {f.family for f in fields.values()}
    for rule in _rules():
        target = rule["applies_to"]
        assert set(target.get("fields", [])) <= set(fields)
        if "family" in target:
            assert target["family"] in families
        for group in (rule["groups_open"] or []) + [s["group"] for s in rule.get("groups_with_step", [])]:
            assert group in known_groups()
        for step in rule.get("groups_with_step", []):
            assert set(step.get("scope_fields") or []) <= set(fields)


def test_every_rule_has_https_source_and_confidence():
    for rule in _rules():
        assert rule["confidence"] in CONFIDENCE
        assert rule["sources"] and all(s.startswith("https://") for s in rule["sources"])


def test_every_study_field_resolves_to_a_rule():
    assert [k for k in study_fields() if rule_for(k) is None] == []


def test_field_rule_beats_family_rule():
    assert rule_for("mbbs").groups_open == ["pre_medical"]
    assert rule_for("mbbs").years == 5
    assert rule_for("zoology").confidence == "uncertain"
    assert rule_for("nope") is None


def test_pre_medical_step_on_engineering_is_scoped():
    steps = [s for s in rule_for("civil_engineering").groups_with_step if s.group == "pre_medical"]
    assert steps and set(steps[0].scope_fields) == {"civil_engineering", "electrical_engineering", "mechanical_engineering"}


def test_ibcc_percent_averages_table():
    table = load_data("admission_rules.json")["equivalence"]["o_level_a_level"]["grade_to_pak_marks_a_level_o_level"]
    assert ibcc_percent(["A", "A", "B"]) == (table["A"] * 2 + table["B"]) / 3
    assert ibcc_percent(["A*"]) == 90
    assert ibcc_percent([]) is None and ibcc_percent(["Z"]) is None


def test_years_per_field_override():
    assert rule_for("mbbs").years_for("mbbs") == 5
    assert rule_for("bds").years_for("bds") == 4


def test_null_groups_open_means_use_study_field_open_to():
    """None is the contract: the roadmap engine falls back to open_to in study_fields.json."""
    for key in ("zoology", "food_science", "hospitality_tourism", "sports_sciences"):
        assert rule_for(key).groups_open is None
