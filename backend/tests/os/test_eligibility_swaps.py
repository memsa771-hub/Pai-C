"""Slice 4 Task 6: swap suggestions (spec S4-D5). Cards are built directly; no route, fact or student is real."""

from app.os.eligibility.evaluate import Card, Line
from app.os.eligibility.swaps import Suggestion, suggest


def card(ref, **lines) -> Card:
    ls = [Line(check.replace("_", ":"), status) for check, status in lines.items()]
    order = ("likely_below", "needs_input", "unknown", "likely_meets")
    return Card(ref, min((ln.status for ln in ls), key=order.index), ls)


MINE = card("mine", grade="likely_meets", language_english="likely_below")  # failing only on English


def test_only_eligible_on_failing_lines():
    candidates = [
        (card("a", grade="likely_below", language_english="likely_meets"), 3),  # meets English: suggested
        (card("b", grade="likely_meets", language_english="likely_below"), 9),  # same problem: not suggested
        (card("c", grade="needs_input", language_english="likely_meets"), 1),  # grade unknown to us: still fine
    ]
    assert [s.programme_ref for s in suggest(MINE, candidates, chosen=set())] == ["a", "c"]


def test_excludes_chosen_and_itself():
    candidates = [(card("mine", language_english="likely_meets"), 5), (card("a", language_english="likely_meets"), 1),
                  (card("d", language_english="likely_meets"), 4)]
    assert [s.programme_ref for s in suggest(MINE, candidates, chosen={"d"})] == ["a"]


def test_ranked_by_confirmed_facts_then_ref():
    candidates = [(card(r, language_english="likely_meets"), n) for r, n in (("b", 2), ("a", 2), ("c", 7))]
    assert suggest(MINE, candidates, chosen=set()) == [Suggestion("c", 7), Suggestion("a", 2), Suggestion("b", 2)]


def test_at_most_three():
    candidates = [(card(f"p{i}", language_english="likely_meets"), i) for i in range(6)]
    assert len(suggest(MINE, candidates, chosen=set())) == 3


def test_none_when_already_meets():
    good = card("mine", grade="likely_meets", language_english="likely_meets")
    assert suggest(good, [(card("a", language_english="likely_meets"), 1)], chosen=set()) == []


def test_candidate_missing_the_line_not_suggested():
    # a candidate whose card has no English line (its route has no English check) cannot fix an English problem
    assert suggest(MINE, [(card("a", grade="likely_meets"), 3)], chosen=set()) == []


def test_needs_input_card_suggests_only_for_below_lines():
    waiting = card("mine", grade="needs_input", language_english="likely_meets")
    assert suggest(waiting, [(card("a", grade="likely_meets", language_english="likely_meets"), 1)],
                   chosen=set()) == []  # nothing is wrong yet: the student has a document to upload
