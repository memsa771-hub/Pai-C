"""P2-T10: MeritCheck (P2-D26; R-31, R-48, row 6.25). Fictional programmes, bodies and students; `.test` sources.
A verified fact is written only through set_status(..., cause="review")."""

from datetime import UTC, datetime

import pytest

from app.os.contracts.merit_check import MeritCheckV1
from app.os.contracts.route_contract import IntakeRef
from app.os.contracts.student_facts import StudentFactsV1
from app.os.eligibility.facts import current_types
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from app.os.merit_check import build
from app.os.requests.state import scale_pairs

pytestmark = pytest.mark.req("R-31")
AT = datetime(2026, 11, 1, tzinfo=UTC)
URL = "https://admissions.alpha.test/merit"
INTAKE = IntakeRef(term="fall", year=2027)
P1V, P1T = "education.intermediate.part1.marks_obtained", "education.intermediate.part1.marks_total"
P2V, P2T = "education.intermediate.part2.marks_obtained", "education.intermediate.part2.marks_total"
FORMULA = {"parts": [{"name": "part_one", "marks_part": P1V, "weight": 0.6},
                     {"name": "part_two", "marks_part": P2V, "weight": 0.4}], "total": 1000}
PAIRS = scale_pairs(current_types())


def student(**marks) -> StudentFactsV1:
    """marks: key -> (value, evidence)"""
    return StudentFactsV1.model_validate({
        "schema": "pai.student_facts.v1", "student_ref": "stu-1", "vault_version": 1, "built_at": AT.isoformat(),
        "eligible_levels": None,
        "facts": [{"key": k, "value": v, "evidence": e, "vault_version": 1} for k, (v, e) in marks.items()]})


FULL = {P1V: (900, "shown"), P1T: (1100, "shown"), P2V: (800, "stated"), P2T: (1100, "confirmed")}


def put(k, field, value, year=2027, status="confirmed", term="fall", verified=False, ref="p1", **kw) -> int:
    f = Fact(value, "the quote" if status != "unconfirmed" else "", URL if status != "unconfirmed" else "", AT, year,
             status, intake_term=term, **kw)
    fid = k.upsert("programme", ref, field, f)
    if verified:
        k.set_status(fid, "verified", cause="review", actor="checker-test")
    return fid


@pytest.fixture
def k(engine, clean):
    return SqlKnowledge(engine, "pai")


def test_computed_from_a_verified_formula_and_the_vaults_marks(k):
    put(k, "merit_formula", FORMULA, verified=True, owner_ref="body:board")
    got = build(k, student(**FULL), "p1", INTAKE, None, PAIRS)
    assert got.status == "computed" and got.formula.level == "verified" and got.formula.owner_ref == "body:board"
    expected = (0.6 * 900 / 1100 * 100 + 0.4 * 800 / 1100 * 100) * 1000 / 100
    assert got.aggregate == pytest.approx(expected, abs=1e-5)
    assert {m.key: m.evidence for m in got.marks_used} == {P1V: "shown", P2V: "stated"}  # the weaker of mark and total
    assert [p.status for p in got.parts] == ["known", "known"]
    assert got.formula.source.url == URL
    MeritCheckV1.model_validate_json(got.model_dump_json(by_alias=True))  # the contract round-trips


@pytest.mark.parametrize("status,verified", [("confirmed", False), ("unconfirmed", False)])
def test_not_confirmed_unless_the_formula_is_verified(k, status, verified):
    put(k, "merit_formula", FORMULA, status=status, verified=verified)
    got = build(k, student(**FULL), "p1", INTAKE, None, PAIRS)
    assert got.status == "not_confirmed" and got.aggregate is None and got.formula is None and got.parts == []
    assert "weight" not in got.model_dump_json()  # an unverified formula's values do not travel


def test_not_confirmed_without_any_formula(k):
    got = build(k, student(**FULL), "p1", INTAKE, None, PAIRS)
    assert got.status == "not_confirmed" and got.formula is None


def test_a_formula_of_another_year_or_term_does_not_count(k):
    put(k, "merit_formula", FORMULA, year=2026, verified=True)
    put(k, "merit_formula", FORMULA, term="spring", verified=True)
    assert build(k, student(**FULL), "p1", INTAKE, None, PAIRS).status == "not_confirmed"


def test_missing_mark_names_the_part(k):
    put(k, "merit_formula", FORMULA, verified=True)
    got = build(k, student(**{P1V: (900, "shown"), P1T: (1100, "shown")}), "p1", INTAKE, None, PAIRS)
    assert got.status == "missing" and got.aggregate is None
    assert [(p.name, p.status) for p in got.parts] == [("part_one", "known"), ("part_two", "missing")]
    assert [(m.key, m.evidence) for m in got.marks_used] == [(P1V, "shown"), (P2V, "unknown")]


def test_an_impossible_mark_is_not_confirmed_and_an_absent_one_is_missing(k):
    """The reason a part is not known sits in the contract's own words (M1): absent = missing; held but unusable =
    not_confirmed, and the marks the Vault holds are shown."""
    put(k, "merit_formula", FORMULA, verified=True)
    bad = {**FULL, P2V: (1200, "stated")}  # above its total
    got = build(k, student(**bad), "p1", INTAKE, None, PAIRS)
    assert got.status == "not_confirmed" and got.aggregate is None
    assert {p.name: p.status for p in got.parts} == {"part_one": "known", "part_two": "not_confirmed"}
    assert next(m for m in got.marks_used if m.key == P2V).value == 1200
    both = student(**{P2V: (1200, "stated"), P2T: (1100, "shown")})  # part one absent, part two impossible
    mixed = build(k, both, "p1", INTAKE, None, PAIRS)
    assert mixed.status == "missing" and {p.name: p.status for p in mixed.parts} == {
        "part_one": "missing", "part_two": "not_confirmed"}


def test_two_different_totals_are_not_guessed(k):
    put(k, "merit_formula", FORMULA, verified=True)
    pairs = [*PAIRS, (P1V, "education.other.marks_total")]
    two = {**FULL, "education.other.marks_total": (1000, "shown")}  # P1 now has totals 1100 and 1000
    got = build(k, student(**two), "p1", INTAKE, None, pairs)
    assert got.status == "not_confirmed" and got.parts[0].status == "not_confirmed" and got.aggregate is None
    same = {**FULL, "education.other.marks_total": (1100, "shown")}  # the same total twice is one total
    assert build(k, student(**same), "p1", INTAKE, None, pairs).status == "computed"
    only_other = {k_: v for k_, v in two.items() if k_ != P1T}  # one of them held: that one is used
    assert build(k, student(**only_other), "p1", INTAKE, None, pairs).status == "computed"


def test_category_formula_and_fallback_to_the_general_one(k):
    put(k, "merit_formula", FORMULA, verified=True)
    other = {"parts": [{"name": "part_one", "marks_part": P1V, "weight": 1.0}], "total": 100}
    put(k, "merit_formula_open_seats", other, verified=True)
    cat = build(k, student(**FULL), "p1", INTAKE, "open_seats", PAIRS)
    assert cat.formula.total == 100 and cat.aggregate == pytest.approx(900 / 1100 * 100, abs=1e-5)
    assert cat.category == "open_seats"
    general = build(k, student(**FULL), "p1", INTAKE, "other_seats", PAIRS)
    assert general.formula.total == 1000
    assert general.category is None  # M3: the general formula answered, so the answer names no category


def test_closing_merits_by_year_with_levels_and_lists(k):
    later = IntakeRef(term="fall", year=2028)
    put(k, "merit_formula", FORMULA, year=2028, verified=True)
    put(k, "closing_merit", {"value": 812.5, "list_number": 3, "list_complete": True}, year=2027, verified=True)
    put(k, "closing_merit", {"value": 790.0, "list_number": 1, "list_complete": False}, year=2026, verified=True)
    put(k, "closing_merit", {"value": 801.0, "list_number": 2, "list_complete": True}, year=2025)  # only confirmed
    got = build(k, student(**FULL), "p1", later, None, PAIRS)
    by_year = {c.intake.year: c for c in got.closing_merits}
    assert [c.intake.year for c in got.closing_merits] == [2027, 2026, 2025]
    assert by_year[2027].value == 812.5 and by_year[2027].list_complete and by_year[2027].level == "verified"
    assert by_year[2026].value == 790.0 and not by_year[2026].list_complete and by_year[2026].list_number == 1
    assert by_year[2025].value is None and by_year[2025].level == "not_confirmed"  # high-stakes: not shown as fact
    assert by_year[2025].source.url == URL  # but the link is given


def test_closing_merits_appear_even_when_the_formula_is_not_confirmed(k):
    put(k, "closing_merit", {"value": 812.5, "list_number": 3, "list_complete": True}, year=2026, verified=True)
    got = build(k, student(**FULL), "p1", INTAKE, None, PAIRS)
    assert got.status == "not_confirmed" and [c.intake.year for c in got.closing_merits] == [2026]


def test_there_is_no_chance_or_prediction_field():
    names = " ".join(MeritCheckV1.model_json_schema()["properties"]) + str(MeritCheckV1.model_json_schema())
    for word in ("chance", "probab", "predict", "likel"):
        assert word not in names.lower()


def test_a_closing_merit_with_no_recorded_term_says_so(k):
    later = IntakeRef(term="fall", year=2028)
    put(k, "closing_merit", {"value": 700.0, "list_number": 1, "list_complete": True}, year=2027, term="", verified=True)
    got = build(k, student(**FULL), "p1", later, None, PAIRS)
    assert [(c.intake.term, c.intake.year) for c in got.closing_merits] == [("unrecorded", 2027)]  # not guessed (M2)


def test_the_year_floor_comes_from_the_contract():
    from app.os.knowledge import merit

    assert merit.intake_year_floor() == 2025
