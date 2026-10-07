from app.inference.client import _reasoning_effort_for


def test_minimal_effort_maps_to_supported_gpt_54_value():
    assert _reasoning_effort_for("gpt-5.4-mini", "minimal", False) == "none"
    assert _reasoning_effort_for("gpt-5.4-mini", "low", False) == "low"
    assert _reasoning_effort_for("gpt-5-mini", "minimal", False) == "minimal"
