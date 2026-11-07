"""P2-T10: merit formula and closing-merit fact shapes (P2-D26; R-31)."""

import pytest

from app.os.knowledge import merit
from app.os.knowledge.merit import MeritShapeError

pytestmark = pytest.mark.req("R-31")
PART = {"name": "part_one", "marks_part": "education.x.marks_obtained", "weight": 1.0}


def test_formula_shape():
    f = merit.parse_formula({"parts": [PART], "total": 1100})
    assert f.total == 1100 and f.parts[0].name == "part_one"
    two = [{**PART, "weight": 0.5}, {**PART, "name": "part_two", "weight": 0.5}]
    assert len(merit.parse_formula({"parts": two, "total": 100}).parts) == 2


@pytest.mark.parametrize("value", [
    None, {}, {"parts": [PART]}, {"parts": [], "total": 100}, {"parts": [PART], "total": 0},
    {"parts": [{**PART, "weight": 0.5}], "total": 100},  # weights do not add up to 1
    {"parts": [{**PART, "name": "Bad Name"}], "total": 100},
    {"parts": [{**PART, "marks_part": ""}], "total": 100},
    {"parts": [{**PART, "weight": True}], "total": 100},
    {"parts": [{**PART, "weight": 0.5}, {**PART, "weight": 0.5}], "total": 100},  # duplicate name
    {"parts": [PART], "total": 100, "extra": 1},
])
def test_bad_formulas_refused(value):
    with pytest.raises(MeritShapeError):
        merit.parse_formula(value)


def test_closing_merit_shape_and_the_incomplete_list_rule():
    ok = merit.parse_closing({"value": 800.5, "list_number": 2, "list_complete": True})
    assert ok.list_complete and ok.list_number == 2
    assert merit.parse_closing({"value": 800, "list_number": None, "list_complete": True}).list_number is None
    for bad in ({"value": 800, "list_number": None, "list_complete": False},  # "lowest on list N" needs N
                {"value": "800", "list_number": 1, "list_complete": True},
                {"value": 800, "list_number": 0, "list_complete": True},
                {"value": 800, "list_complete": True}):
        with pytest.raises(MeritShapeError):
            merit.parse_closing(bad)


def test_fields_and_categories():
    assert merit.is_merit_field("merit_formula") == "formula"
    assert merit.is_merit_field("closing_merit_open_seats") == "closing"
    assert merit.is_merit_field("deadline_close") is None
    assert merit.is_merit_field("closing_meritorious") is None
    assert merit.field_for("merit_formula", "Seat Category:Open-1") == "merit_formula_seat_category_open_1"
    assert merit.field_for("merit_formula", None) == "merit_formula"


def test_the_service_refuses_a_bad_merit_value_before_it_is_stored():
    from app.os.service import PlanService

    check = PlanService.check_fact_value
    stub = type("S", (), {"anchor_fields": lambda self: set()})()
    check(stub, "merit_formula", {"parts": [PART], "total": 100})
    with pytest.raises(MeritShapeError):
        check(stub, "closing_merit", {"value": 1})
    check(stub, "anything_else", "x")


def test_merit_fields_are_high_stakes_classes():
    from app.os.knowledge.fact_classes import fact_class, is_high_stakes

    for field in ("merit_formula", "closing_merit"):
        assert is_high_stakes(fact_class(field))
