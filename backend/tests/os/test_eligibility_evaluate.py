"""Slice 4 Task 3: evaluate, the same code on every route (spec S4-D2, S4-D3, S4-D5). Synthetic values only."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.os.eligibility.evaluate import evaluate
from app.os.knowledge.port import Fact
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir

BOOKS = load_playbook_dir(PLAYBOOK_DIR) | load_playbook_dir(Path(__file__).parent / "playbooks")
DE = BOOKS[("germany_master", 1)].eligibility
IE = BOOKS[("ireland_master", 1)].eligibility
PK = BOOKS[("pakistan_bs", 1)].eligibility


def fact(value, status="confirmed", field_url="https://uni.example/req") -> Fact:
    return Fact(value=value, quote="q" if status == "confirmed" else "", url=field_url,
                checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc), intake_year=2027, status=status)


DE_FACTS = {"grade_requirement": fact({"german_max": 2.5}),
            "english_requirement": fact({"cefr": "B2", "ielts": 6.5}),
            "german_requirement": fact({"level": "none"}),
            "admission_test": fact(None)}
IE_FACTS = {"grade_requirement": fact({"percent_min": 60}), "english_requirement": fact({"ielts": 6.5})}
PK_FACTS = {"merit_closing": fact({"aggregate": 80}), "entry_test_required": fact({"any_of": []})}

STRONG = {"transcript.cgpa": 3.2, "transcript.percentage": 75, "ielts_trf.overall": 7.0,
          "hssc_certificate.marks_obtained": 990, "hssc_certificate.marks_total": 1100, "entry_test.score": 80}
WEAK = {"transcript.cgpa": 2.6, "transcript.percentage": 55, "ielts_trf.overall": 6.0,
        "hssc_certificate.marks_obtained": 770, "hssc_certificate.marks_total": 1100, "entry_test.score": 60}

ROUTES = {"germany": (DE, DE_FACTS), "ireland": (IE, IE_FACTS), "pakistan_bs": (PK, PK_FACTS)}


def line(card, check):
    return next(ln for ln in card.lines if ln.check == check)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_meets_and_below(route):
    rules, facts = ROUTES[route]
    assert line(evaluate(rules, "p", facts, STRONG), "grade").status == "likely_meets"
    assert line(evaluate(rules, "p", facts, WEAK), "grade").status == "likely_below"


def test_germany_numbers():
    g = line(evaluate(DE, "p", DE_FACTS, STRONG), "grade")
    assert (g.have, g.need, g.provisional) == (2.2, 2.5, True)  # 1 + 3 * 0.8 / 2.0 = 2.2, typical minimum pass
    e = line(evaluate(DE, "p", DE_FACTS, WEAK), "language:english")
    assert (e.status, e.have, e.need) == ("likely_below", 6.0, 6.5)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_boundary_meets(route):
    rules, facts = ROUTES[route]
    exact = {"germany": {"transcript.cgpa": 3.0},  # -> 2.5, needs 2.5
             "ireland": {"transcript.percentage": 60},  # needs 60
             "pakistan_bs": {"hssc_certificate.marks_obtained": 880, "hssc_certificate.marks_total": 1100,
                             "entry_test.score": 80}}[route]  # 0.5 * 80 + 0.5 * 80 = 80, needs 80
    assert line(evaluate(rules, "p", facts, exact), "grade").status == "likely_meets"


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_missing_value_needs_input_names_document(route):
    rules, facts = ROUTES[route]
    g = line(evaluate(rules, "p", facts, {}), "grade")
    assert g.status == "needs_input" and g.have is None
    assert set(g.needs) <= {"transcript", "hssc_certificate", "entry_test"} and g.needs


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_missing_fact_unknown(route):
    rules, _ = ROUTES[route]
    card = evaluate(rules, "p", {}, STRONG)
    assert line(card, "grade").status == "unknown" and card.verdict in ("unknown", "needs_input")


def test_open_finding_blocks_value():
    card = evaluate(DE, "p", DE_FACTS, STRONG, held=frozenset({"transcript.cgpa", "transcript.percentage"}))
    g = line(card, "grade")
    assert g.status == "needs_input" and g.reason == "open_finding" and g.have is None


def test_provisional_default_flagged():
    assert line(evaluate(DE, "p", DE_FACTS, STRONG), "grade").provisional
    assert not line(evaluate(IE, "p", IE_FACTS, STRONG), "grade").provisional  # threshold uses no minimum pass


def test_verdict_is_worst_line():
    card = evaluate(DE, "p", DE_FACTS, {"transcript.cgpa": 3.2, "ielts_trf.overall": 6.0})
    assert line(card, "grade").status == "likely_meets"
    assert card.verdict == "likely_below"
    assert evaluate(DE, "p", DE_FACTS, {"transcript.cgpa": 3.2}).verdict == "needs_input"


def test_grade_checks_tried_in_order():
    facts = DE_FACTS | {"grade_requirement": fact({"german_max": None, "percent_min": 70})}
    g = line(evaluate(DE, "p", facts, STRONG), "grade")
    assert (g.status, g.have, g.need) == ("likely_meets", 75, 70)  # the threshold check decided


def test_language_none_meets():
    assert line(evaluate(DE, "p", DE_FACTS, {}), "language:german").status == "likely_meets"


def test_german_level_without_proof_needs_input():
    facts = DE_FACTS | {"german_requirement": fact({"level": "B1"})}
    ln = line(evaluate(DE, "p", facts, STRONG), "language:german")
    assert (ln.status, ln.need, ln.reason) == ("needs_input", "B1", "no_proof_type")


def test_test_lines():
    assert line(evaluate(DE, "p", DE_FACTS, STRONG), "test").status == "likely_meets"  # none required
    t = line(evaluate(DE, "p", DE_FACTS | {"admission_test": fact({"any_of": ["GRE"]})}, STRONG), "test")
    assert (t.status, t.need) == ("needs_input", ["GRE"])


def test_sources_carry_fact_status():
    facts = DE_FACTS | {"english_requirement": fact({"ielts": 6.5}, status="unconfirmed")}
    e = line(evaluate(DE, "p", facts, STRONG), "language:english")
    assert [(s.field, s.status) for s in e.sources] == [("english_requirement", "unconfirmed")]


def test_two_routes_one_request_use_their_own_rules():
    profile = STRONG | {"transcript.percentage": 62}
    de = evaluate(DE, "p", DE_FACTS | {"grade_requirement": fact({"percent_min": 70})}, profile)
    ie = evaluate(IE, "p", IE_FACTS, profile)
    assert line(de, "grade").status == "likely_below" and line(ie, "grade").status == "likely_meets"
    assert [ln.check for ln in ie.lines] == ["grade", "language:english"]  # no German, no test on this route
    assert [ln.check for ln in evaluate(PK, "p", PK_FACTS, profile).lines] == ["grade", "test"]


def test_non_numeric_value_needs_input():
    g = line(evaluate(DE, "p", DE_FACTS, {"transcript.cgpa": "three"}), "grade")
    assert g.status == "needs_input" and g.reason == "not_a_number"


def test_no_country_terms_scan_covers_eligibility():
    from tests.os.test_invariants import APP_OS

    assert (APP_OS / "eligibility" / "evaluate.py").is_file()  # the red-flag test scans app/os recursively
