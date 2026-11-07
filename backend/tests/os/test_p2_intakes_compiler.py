"""P2-T8: a fact of another intake is labelled and never firm in the compiler (P2-D24; R-26, R-63)."""

from datetime import date

import pytest

from app.os.compiler import compile_plan
from tests.os.test_compiler import IE, contract, fact, task
from dataclasses import replace

pytestmark = pytest.mark.req("R-26")
TODAY = date(2026, 11, 20)  # the 2027 intake is being planned; the 2026 cycle's deadlines are in the future or past


def last_year(day, status="confirmed"):
    return replace(fact({"date": day}, status), intake_year=2026)


def test_flag_off_is_the_old_draft():
    facts = {("p1", "deadline_close"): fact({"date": "2027-07-15"})}
    d = compile_plan(contract(["p1"]), IE, {}, facts, date(2027, 3, 1))
    assert not task(d, "apply@p1").provisional
    assert all("intake_year" not in c for c in task(d, "apply@p1").citations)


def test_previous_year_fact_is_provisional_labelled_and_checked():
    d = compile_plan(contract(["p1"]), IE, {}, {("p1", "deadline_close"): last_year("2027-01-10")}, TODAY)
    apply = task(d, "apply@p1")
    assert apply.provisional and apply.latest_finish is not None
    assert [c["intake_year"] for c in apply.citations if "intake_year" in c] == [2026]
    assert task(d, "confirm_fact@p1:deadline_close")  # the new year's value is to be confirmed
    assert ("programme", "p1", "deadline_close") in apply.fact_refs  # no year in the ref: the new fact revises it


def test_a_past_date_of_the_previous_year_dates_nothing():
    d = compile_plan(contract(["p1"]), IE, {}, {("p1", "deadline_close"): last_year("2026-07-15")}, TODAY)
    assert task(d, "apply@p1").blocked_reason == "fact_missing:deadline_close"
    assert task(d, "confirm_fact@p1:deadline_close")


def test_the_new_years_fact_replaces_it():
    new = {("p1", "deadline_close"): fact({"date": "2027-01-20"})}
    d = compile_plan(contract(["p1"]), IE, {}, new, TODAY)
    apply = task(d, "apply@p1")
    assert not apply.provisional and not [t for t in d.tasks if t.task_type == "knowledge.confirm_fact"]
