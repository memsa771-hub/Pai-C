"""P2-T8: the yearly rollover, the expected slots, the export and the term backfill (§4.8; R-61, R-62, D-t1-1).
Fictional routes and `.test` sites."""

import csv
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.os import models
from app.os.intakes import IntakeError, IntakeStore
from app.os.intakes.rollover import backfill_intake_terms, export_csv, rollover, slot_report
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import load_playbook
from tests.os.test_compiler import FAKE

pytestmark = pytest.mark.req("R-61")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
GATE = datetime(2026, 10, 1, tzinfo=UTC)


def fact(year, value, status="confirmed", term="fall", **kw) -> Fact:
    return Fact(value=value, quote="q" if status != "unconfirmed" else "",
                url="https://admissions.alpha.test/n" if status != "unconfirmed" else "", checked_at=AT,
                intake_year=year, status=status, intake_term=term, **kw)


def seed_2026(engine):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p1", "deadline_close", fact(2026, {"date": "2026-12-15"}))
    k.upsert("programme", "p1", "fee", fact(2026, 50, owner_ref="body:board"))
    k.upsert("route", "r1", "funds", fact(2026, 11000))
    k.upsert("programme", "p1", "deadline_close", fact(2025, {"date": "2025-12-15"}))  # an older year: not copied
    s = IntakeStore(engine, "pai")
    i = s.create("r_one", "undergrad", "fall", 2026, state="open")
    s.set_state(i.id, "current", gate_passed_at=GATE)
    return k, s, i


def test_rollover_opens_the_intake_and_copies_keys_not_values(engine, clean):
    k, s, prev = seed_2026(engine)
    res = rollover(engine, "pai", region="r_one", family="undergrad", term="fall", year=2027)
    new = s.get("r_one", "undergrad", "fall", 2027)
    assert new.state == "open" and new.opened_from_id == prev.id and res.intake.id == new.id
    assert res.slots_added == 3
    rep = slot_report(engine, "pai", new.id)
    assert {(r.scope, r.ref, r.field, r.owner_ref) for r in rep} == {
        ("programme", "p1", "deadline_close", ""), ("programme", "p1", "fee", "body:board"),
        ("route", "r1", "funds", "")}
    assert {r.state for r in rep} == {"expected"}
    assert k.programme_facts(["p1"], ["deadline_close", "fee"], 2027) == {}  # no value copied
    # the previous intake is untouched and still readable with its year
    assert k.programme_facts(["p1"], ["deadline_close"], 2026)[("p1", "deadline_close")].value == {"date": "2026-12-15"}
    assert s.get("r_one", "undergrad", "fall", 2026).state == "current"
    # no fact, so no revision either
    with engine.connect() as conn:
        assert conn.execute(select(models.fact_revisions.c.cause).where(
            models.fact_revisions.c.cause == "rollover")).first() is None


def test_rollover_twice_adds_nothing_and_slots_fill_from_facts(engine, clean):
    k, s, _ = seed_2026(engine)
    rollover(engine, "pai", region="r_one", family="undergrad", term="fall", year=2027)
    again = rollover(engine, "pai", region="r_one", family="undergrad", term="fall", year=2027)
    assert again.slots_added == 0
    k.upsert("programme", "p1", "deadline_close", fact(2027, {"date": "2027-12-15"}, status="unconfirmed"))
    rep = {(r.ref, r.field): r for r in slot_report(engine, "pai", again.intake.id)}
    assert rep[("p1", "deadline_close")].state == "unconfirmed"
    assert rep[("p1", "fee")].state == "expected"


def test_two_terms_in_one_year_do_not_mix(engine, clean):
    k, s, _ = seed_2026(engine)
    k.upsert("programme", "p2", "deadline_close", fact(2026, {"date": "2026-04-01"}, term="spring"))
    sp = s.create("r_one", "undergrad", "spring", 2026, state="open")
    res = rollover(engine, "pai", region="r_one", family="undergrad", term="spring", year=2027)
    assert res.intake.opened_from_id == sp.id
    assert [(r.ref, r.field) for r in slot_report(engine, "pai", res.intake.id)] == [("p2", "deadline_close")]


def test_rollover_refuses_a_bad_term_and_a_closed_target(engine, clean):
    seed_2026(engine)
    with pytest.raises(Exception, match="monsoon"):
        rollover(engine, "pai", region="r_one", family="undergrad", term="monsoon", year=2027)
    s = IntakeStore(engine, "pai")
    c = s.create("r_one", "undergrad", "fall", 2027, state="open")
    s.set_state(c.id, "closed")
    with pytest.raises(IntakeError, match="closed"):
        rollover(engine, "pai", region="r_one", family="undergrad", term="fall", year=2027)


def test_first_intake_has_no_previous(engine, clean):
    res = rollover(engine, "pai", region="r_one", family="undergrad", term="fall", year=2027)
    assert res.intake.state == "open" and res.intake.opened_from_id is None and res.slots_added == 0


def test_export_is_prefilled_with_last_years_labelled_values(engine, clean, tmp_path):
    seed_2026(engine)
    res = rollover(engine, "pai", region="r_one", family="undergrad", term="fall", year=2027)
    out = tmp_path / "slots.csv"
    assert export_csv(engine, "pai", res.intake.id, out) == 3
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    fee = next(r for r in rows if r["field"] == "fee")
    assert (fee["intake_term"], fee["intake_year"], fee["owner_ref"]) == ("fall", "2027", "body:board")
    assert (fee["previous_year"], fee["previous_value"], fee["previous_status"]) == ("2026", "50", "confirmed")
    assert fee["new_value"] == "" and fee["new_url"] == "" and fee["new_quote"] == ""


def test_backfill_sets_the_term_from_the_playbook(engine, clean):
    one = load_playbook(FAKE / "ireland_master.v1.yaml")  # a single declared term
    assert len(one.intake_terms) == 1
    two = one.model_copy(update={"key": "two_terms", "intake_terms": ["spring", "fall"]})
    none = one.model_copy(update={"key": "no_terms", "intake_terms": []})
    books = {(b.key, b.version): b for b in (one, two, none)}
    k = SqlKnowledge(engine, "pai")
    with engine.begin() as conn:
        conn.execute(insert(models.programmes), [
            {"tenant_id": "pai", "ref": ref, "route_key": rk, "university": "u", "name": "n"}
            for ref, rk in (("pa", one.key), ("pb", "two_terms"), ("pc", "no_terms"))])
    legacy = dict(value=1, quote="q", url="https://a.test/x", checked_at=AT, status="confirmed")
    for ref in ("pa", "pb", "pc", "ghost"):
        k.upsert("programme", ref, "fee", Fact(intake_year=2027, **legacy))
    k.upsert("route", one.key, "funds", Fact(intake_year=2027, **legacy))
    k.upsert("programme", "pa", "fee", Fact(intake_year=2028, intake_term="spring", **legacy))  # already has a term
    res = backfill_intake_terms(engine, "pai", books)
    assert res.updated == 2
    assert {(r.ref, r.reason) for r in res.skipped} == {("pb", "several_terms"), ("pc", "no_term"),
                                                         ("ghost", "unknown_ref")}
    got = {(f.ref, f.intake_year): f.intake_term for f in _all(engine)}
    assert got[("pa", 2027)] == one.intake_terms[0] and got[(one.key, 2027)] == one.intake_terms[0]
    assert got[("pb", 2027)] == "" and got[("pa", 2028)] == "spring"
    assert backfill_intake_terms(engine, "pai", books).updated == 0  # idempotent


def test_backfill_keeps_the_newer_row_when_the_key_is_taken(engine, clean):
    one = load_playbook(FAKE / "ireland_master.v1.yaml")
    term = one.intake_terms[0]
    with engine.begin() as conn:
        conn.execute(insert(models.programmes).values(tenant_id="pai", ref="pa", route_key=one.key, university="u",
                                                      name="n"))
    k = SqlKnowledge(engine, "pai")
    base = dict(value=1, quote="q", url="https://a.test/x", checked_at=AT, status="confirmed", intake_year=2027)
    k.upsert("programme", "pa", "fee", Fact(**base))
    k.upsert("programme", "pa", "fee", Fact(intake_term=term, **base))
    res = backfill_intake_terms(engine, "pai", {(one.key, 1): one})
    assert res.updated == 0 and [r.reason for r in res.skipped] == ["key_taken"]


def _all(engine):
    with engine.connect() as conn:
        return conn.execute(select(models.knowledge_facts)).all()
