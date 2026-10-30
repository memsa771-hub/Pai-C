"""The admin fallback script for a fact research cannot find (Slice 9b entry condition 2): `scripts.os_supply_fact`.

It calls the same service code as POST /v1/os/facts and POST /v1/os/facts/{id}/confirm, with the same request
models, so it validates exactly as the API does. Fictional programme dates and URLs only.
"""

import json

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge import SqlKnowledge
from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed
from scripts import os_supply_fact
from tests.os.test_api_replan import api  # noqa: F401  (a fixture: a plan for the golden test student)

T, F = models.tasks, models.knowledge_facts
REF = "ovgu-eeit"  # one of the test student's programmes
URL = "https://uni.example/ovgu-eeit/academic-calendar"  # fictional
QUOTE = "Classes: October 11, 2027 - January 28, 2028"


@pytest.fixture
def svc(api):  # noqa: F811
    load_programme_seed(PROGRAMME_SEED, ProgrammeStore(api.engine, "pai"))
    with api.engine.begin() as conn:  # research ran and found no date: its check waits for an admin (simulated)
        conn.execute(T.update().where(T.c.instance_key == f"confirm_fact@{REF}:semester_start")
                     .values(state="waiting_review"))
    return api.svc


def run(svc, *args) -> int:
    return os_supply_fact.main(list(args), services=svc)


def _task(svc, ref=REF):
    with svc.engine.connect() as conn:
        return conn.execute(select(T.c.id, T.c.state).where(
            T.c.instance_key == f"confirm_fact@{ref}:semester_start")).first()


def _fact(svc, ref=REF):
    return SqlKnowledge(svc.engine, "pai").programme_facts([ref], ["semester_start"], 2027).get((ref, "semester_start"))


def test_list_shows_the_open_semester_start_tasks(svc, capsys):
    assert _task(svc).state == "waiting_review"  # the visa step waits for it
    assert run(svc, "list") == 0
    out = capsys.readouterr().out
    assert f"{REF} semester_start" in out and "no fact yet" in out


def test_supply_stores_a_manual_fact_and_completes_the_task(svc, capsys):
    assert run(svc, "supply", "--programme", REF, "--intake", "2027", "--date", "2027-10-11",
               "--url", URL, "--quote", QUOTE) == 0
    fact = _fact(svc)
    assert fact.status == "confirmed" and fact.value == {"date": "2027-10-11", "tz": "Europe/Berlin"}
    assert (fact.url, fact.quote) == (URL, QUOTE)
    with svc.engine.connect() as conn:
        assert conn.execute(select(F.c.source).where(F.c.ref == REF, F.c.field == "semester_start")).scalar() == "manual"
    assert _task(svc).state == "done"
    assert "revised plans" in capsys.readouterr().out


def test_supply_can_leave_the_fact_unconfirmed(svc):
    assert run(svc, "supply", "--programme", REF, "--intake", "2027", "--date", "2027-10-11", "--url", URL,
               "--quote", QUOTE, "--status", "unconfirmed", "--note", "Page shows 2026/27 only") == 0
    fact = _fact(svc)
    assert fact.status == "unconfirmed" and fact.conflict_note == "Page shows 2026/27 only"


@pytest.mark.parametrize("args,msg", [
    (["--date", "2027-13-40"], "not a date"),  # the API's date check (service.check_fact_value)
    (["--date", "2027-10-11", "--status", "maybe"], "status"),  # the API's request model
    (["--date", "2027-10-11", "--quote", ""], "quote"),  # a confirmed fact needs a quote (the trust rule)
    (["--date", "2027-10-11", "--programme", "no-such-programme"], "unknown programme"),
])
def test_supply_rejects_what_the_api_rejects(svc, capsys, args, msg):
    base = {"--programme": REF, "--intake": "2027", "--url": URL, "--quote": QUOTE}
    for k, v in zip(args[::2], args[1::2]):
        base[k] = v
    argv = ["supply", *[x for kv in base.items() for x in kv]]
    assert run(svc, *argv) == 2
    assert msg in capsys.readouterr().err.lower()
    assert _fact(svc) is None and _task(svc).state == "waiting_review"


def test_confirm_corrects_an_existing_fact_by_id(svc, capsys):
    assert run(svc, "supply", "--programme", REF, "--intake", "2027", "--date", "2027-10-04", "--url", URL,
               "--quote", "Lectures start on 4 October 2027", "--status", "unconfirmed") == 0
    fact_id = _fact(svc).id
    assert run(svc, "confirm", "--fact-id", str(fact_id), "--date", "2027-10-11", "--url", URL,
               "--quote", QUOTE) == 0
    fact = _fact(svc)
    assert fact.status == "confirmed" and fact.value["date"] == "2027-10-11" and fact.id == fact_id
    assert run(svc, "confirm", "--fact-id", "999999", "--date", "2027-10-11", "--url", URL, "--quote", QUOTE) == 2
    assert "fact not found" in capsys.readouterr().err


def test_show_prints_what_research_found(svc, capsys):
    evidence = [{"reading": "A", "value": "10-12", "quote": "Begin of lectures 12.10.2026", "url": URL,
                 "cycle": "2026/27", "scope_quote": None, "reasons": []}]
    from app.os.knowledge import Fact
    from app.os import clock

    SqlKnowledge(svc.engine, "pai").upsert(
        "programme", REF, "semester_start",
        Fact({"date": "2026-10-12", "tz": "Europe/Berlin"}, "Begin of lectures 12.10.2026", URL, clock.now(), 2027,
             "unconfirmed", conflict_note="page shows 2026/27"),
        source="research", evidence=evidence)
    assert run(svc, "show", "--programme", REF, "--intake", "2027") == 0
    out = capsys.readouterr().out
    assert "unconfirmed" in out and "page shows 2026/27" in out and json.dumps(evidence[0]["quote"]) in out
