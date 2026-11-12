"""P2-T1: facts per intake term and owner, the `verified` level and append-only revisions (P2 spec P2-D5, P2-D6,
P2-D8, P2-D9; master R-23, R-25, R-60). Fictional programmes on `.test` domains."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge

pytestmark = pytest.mark.req("R-60")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
T = models.knowledge_facts


def fact(status="confirmed", value="v", **kw) -> Fact:
    return Fact(value=value, quote="the quote", url="https://admissions.alpha.test/notice", checked_at=AT,
                intake_year=2027, status=status, **kw)


def test_new_columns_and_defaults(engine, clean):
    cols = {c["name"]: c for c in inspect(engine).get_columns("os_knowledge_facts", schema="os")}
    for name in ("intake_term", "owner_ref", "fact_class", "read_method", "language"):
        assert name in cols
    assert not cols["intake_term"]["nullable"] and not cols["owner_ref"]["nullable"]
    with engine.begin() as conn:  # a row written the pre-P2 way
        conn.execute(insert(T).values(tenant_id="pai", scope="programme", ref="p", field="f", intake_year=2027,
                                      checked_at=AT, status="unconfirmed"))
        row = conn.execute(select(T)).one()
    assert (row.intake_term, row.owner_ref, row.fact_class, row.read_method, row.language) == ("", "", None, None, None)
    assert "os_fact_revisions" in inspect(engine).get_table_names(schema="os")


def test_key_includes_term_and_owner(engine, clean):
    k = SqlKnowledge(engine, "pai")
    a = k.upsert("programme", "p", "deadline_close", fact(value="a"))
    b = k.upsert("programme", "p", "deadline_close", fact(value="b", intake_term="spring"))
    c = k.upsert("programme", "p", "deadline_close", fact(value="c", owner_ref="body:regulator"))
    assert len({a, b, c}) == 3
    assert k.upsert("programme", "p", "deadline_close", fact(value="a2")) == a


@pytest.mark.req("R-25")
def test_status_and_read_method_checks(engine, clean):
    base = {"tenant_id": "pai", "scope": "programme", "ref": "p", "field": "f", "intake_year": 2027, "checked_at": AT}
    with engine.begin() as conn:
        conn.execute(insert(T).values(**base, status="verified", quote="q", url="u"))
    for bad in ({"status": "bogus"}, {"status": "confirmed", "read_method": "guess", "field": "g"},
                {"status": "confirmed", "language": "Urdu", "field": "h"}):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(insert(T).values(**{**base, **bad}))


@pytest.mark.req("R-25")
def test_fact_rules():
    with pytest.raises(ValueError):
        Fact(value=1, quote="", url="https://x.test", checked_at=AT, intake_year=2027, status="verified")
    with pytest.raises(ValueError):
        fact(read_method="guess")
    assert fact("verified").confirmed and fact("verified").verified
    assert fact("confirmed").confirmed and not fact("confirmed").verified
    assert not fact("unconfirmed").confirmed


def test_round_trip_and_filters(engine, clean):
    k = SqlKnowledge(engine, "pai")
    full = fact("confirmed", intake_term="fall", owner_ref="body:board", fact_class="deadline", read_method="ocr",
                language="ur")
    fid = k.upsert("programme", "p", "deadline_close", full)
    k.set_status(fid, "verified", cause="review", cause_ref="rev:1")
    full = Fact(**{**full.__dict__, "status": "verified"})
    assert k.get(fid)[3] == Fact(**{**full.__dict__, "id": fid})
    assert k.programme_facts(["p"], ["deadline_close"], 2027, owner_ref="") == {}  # '' = general rows only
    assert k.programme_facts(["p"], ["deadline_close"], 2027)[("p", "deadline_close")].id == fid  # None = any owner
    got = k.programme_facts(["p"], ["deadline_close"], 2027, owner_ref="body:board")
    assert got[("p", "deadline_close")].read_method == "ocr"
    assert k.programme_facts(["p"], ["deadline_close"], 2027, intake_term="spring", owner_ref="body:board") == {}
    k.upsert("route", "r", "f", fact(intake_term="fall"))
    assert set(k.route_facts("r", ["f"], 2027)) == {"f"}
    assert k.route_facts("r", ["f"], 2027, intake_term="spring") == {}


@pytest.mark.req("R-23")
def test_revisions_written_on_every_change(engine, clean):
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "p", "f", fact("unconfirmed", value="a"), source="research", cause_ref="run:7")
    k.upsert("programme", "p", "f", fact("unconfirmed", value="a"), source="research")  # no change: no revision
    k.upsert("programme", "p", "f", fact("confirmed", value="b"), cause="import", cause_ref="imp:1", actor="admin")
    k.mark_stale(fid)
    k.set_status(fid, "unconfirmed", cause="report", cause_ref="rep:3")
    k.confirm(fid, value="c", quote="q2", url="https://admissions.alpha.test/n2", status="confirmed")
    revs = k.revisions(fid)
    assert [(r.action, r.cause, r.cause_ref) for r in revs] == [
        ("insert", "research", "run:7"), ("change", "import", "imp:1"), ("status", "monitor", None),
        ("status", "report", "rep:3"), ("change", "manual", None)]
    assert revs[0].before is None and revs[1].before["value"] == "a" and revs[1].after["value"] == "b"
    assert revs[1].actor == "admin"


def test_insert_if_absent_writes_one_revision(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.insert_if_absent("route", "r", "f", fact())
    k.insert_if_absent("route", "r", "f", fact(value="other"))
    fid = k.route_facts("r", ["f"], 2027)["f"].id
    assert [r.action for r in k.revisions(fid)] == ["insert"]


@pytest.mark.req("R-25")
def test_set_status_checks_trust_rule(engine, clean):
    k = SqlKnowledge(engine, "pai")
    with engine.begin() as conn:
        fid = conn.execute(insert(T).values(tenant_id="pai", scope="programme", ref="p", field="f", intake_year=2027,
                                            checked_at=AT, status="unconfirmed").returning(T.c.id)).scalar_one()
    with pytest.raises(ValueError):
        k.set_status(fid, "verified", cause="review")
    with pytest.raises(ValueError):
        k.set_status(fid, "unconfirmed", cause="bogus")
    assert k.revisions(fid) == []


def test_revisions_cannot_lose_their_fact(engine, clean):
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "p", "f", fact())
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_knowledge_facts WHERE id = :i"), {"i": fid})


def test_migration_up_down_up(os_db, engine, clean):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0024"], os_db)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("os_knowledge_facts", schema="os")}
        assert "intake_term" not in cols
        assert "os_fact_revisions" not in inspect(engine).get_table_names(schema="os")
    finally:
        run_alembic(["upgrade", "os@head"], os_db)


def test_owner_resolution_order(engine, clean):
    k = SqlKnowledge(engine, "pai")
    general = k.upsert("programme", "p", "f", fact(value="general"))
    owned = k.upsert("programme", "p", "f", fact(value="board", owner_ref="body:board"))
    k.upsert("programme", "p", "f", fact(value="other", owner_ref="body:other"))
    assert k.programme_facts(["p"], ["f"], 2027, owner_ref="body:board")[("p", "f")].id == owned
    assert k.programme_facts(["p"], ["f"], 2027, owner_ref="body:none")[("p", "f")].id == general
    assert k.programme_facts(["p"], ["f"], 2027)[("p", "f")].id == general  # any owner: the general row first
    assert k.route_facts("r", ["f"], 2027) == {}


@pytest.mark.req("R-25")
def test_verified_only_through_review(engine, clean):
    k = SqlKnowledge(engine, "pai")
    with pytest.raises(ValueError, match="review"):
        k.upsert("programme", "p", "f", fact("verified"))
    with pytest.raises(ValueError, match="review"):
        k.insert_if_absent("programme", "p", "f", fact("verified"))
    fid = k.upsert("programme", "p", "f", fact())
    with pytest.raises(ValueError, match="review"):
        k.confirm(fid, value="v", quote="q", url="https://a.test/x", status="verified")
    with pytest.raises(ValueError, match="review"):
        k.set_status(fid, "verified", cause="import")
    assert k.set_status(fid, "verified", cause="review").verified


@pytest.mark.req("R-25")
@pytest.mark.parametrize("cause", ["research", "import", "monitor"])
def test_write_on_verified_row(engine, clean, cause):
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "p", "f", fact())
    k.set_status(fid, "verified", cause="review")
    k.upsert("programme", "p", "f", fact(), cause=cause)  # same value and quote: stays verified
    assert k.get(fid)[3].status == "verified"
    k.upsert("programme", "p", "f", fact(value="new"), cause=cause, cause_ref="x:1")
    assert k.get(fid)[3].status == "unconfirmed"
    last = k.revisions(fid)[-1]
    assert (last.cause, last.cause_ref, last.before["status"], last.after["status"], last.after["value"]) == (
        cause, "x:1", "verified", "unconfirmed", "new")


def test_mark_stale_handles_verified(engine, clean):
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "p", "f", fact())
    k.set_status(fid, "verified", cause="review")
    assert k.mark_stale(fid) and k.get(fid)[3].status == "stale"
    assert not k.mark_stale(fid)


def test_annotate_records_its_cause(engine, clean):
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "p", "f", fact())
    k.annotate(fid, conflict_note="other value seen", cause="monitor", cause_ref="mon:1", actor="os.monitor")
    last = k.revisions(fid)[-1]
    assert (last.action, last.cause, last.cause_ref, last.actor) == ("change", "monitor", "mon:1", "os.monitor")


def test_other_tenant_cannot_confirm_or_set_status(engine, clean):
    fid = SqlKnowledge(engine, "pai").upsert("programme", "p", "f", fact("unconfirmed"))
    other = SqlKnowledge(engine, "other")
    with pytest.raises(KeyError):
        other.confirm(fid, value="x", quote="q", url="https://a.test/x", status="confirmed")
    with pytest.raises(KeyError):
        other.set_status(fid, "unconfirmed", cause="manual")


def test_upsert_after_lost_insert_race_is_a_change(engine, clean, monkeypatch):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "f", fact(value="first"))
    real = SqlKnowledge._keyed
    calls = {"n": 0}

    def first_miss(self, conn, *a):  # the first lookup misses, as if a concurrent insert had not committed yet
        calls["n"] += 1
        return None if calls["n"] == 1 else real(self, conn, *a)

    monkeypatch.setattr(SqlKnowledge, "_keyed", first_miss)
    fid = k.upsert("programme", "p", "f", fact(value="second"))
    assert [r.action for r in k.revisions(fid)] == ["insert", "change"]
