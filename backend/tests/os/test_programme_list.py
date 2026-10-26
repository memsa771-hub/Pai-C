"""Slice 8 Task 6: the programme-list read function (spec S8-D14): the places the Counsellor may offer for a route
and intake. Fictional data on the fake Ireland route."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.os import ports
from app.os.ports import plan_query
from app.os.contracts.programme_list import ProgrammeListV1
from app.os.contracts.route_contract import IntakeRef
from app.os.knowledge import SqlKnowledge
from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import load_playbook_dir

FAKE = Path(__file__).parent / "playbooks"
CHECKED = datetime(2026, 12, 1, tzinfo=timezone.utc)


@pytest.fixture
def mounted(engine, clean, os_db):
    from app.os.api.services import make_services
    from app.os.settings import load_settings

    svc = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine,
                        playbooks=load_playbook_dir(FAKE) | load_playbook_dir())
    store = ProgrammeStore(engine, "pai")
    for ref, status in (("ie-a", "active"), ("ie-b", "active"), ("ie-c", "excluded")):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="University", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://example.org/{ref}",),
                               official_domains=("example.org",), status=status))
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "ie-a", "deadline_close", Fact("2027-03-01", "Closes 1 March 2027.",
                                                          "https://example.org/ie-a", CHECKED, 2027, "confirmed"))
    kb.upsert("programme", "ie-b", "deadline_close", Fact("2027-03-01", "", "", CHECKED, 2027, "unconfirmed"))
    ports.configure(svc)
    try:
        yield svc
    finally:
        ports.configure(None)


def test_programme_list_confirmed_flag(mounted):
    got = plan_query.programme_list("ireland_master", IntakeRef(term="winter", year=2027))
    assert isinstance(got, ProgrammeListV1)
    assert [(p.programme_ref, p.facts_confirmed) for p in got.programmes] == [("ie-a", True), ("ie-b", False)]
    assert (got.route_key, got.intake.year) == ("ireland_master", 2027)


def test_other_intake_year_not_confirmed(mounted):
    got = plan_query.programme_list("ireland_master", IntakeRef(term="winter", year=2028))
    assert [(p.programme_ref, p.facts_confirmed) for p in got.programmes] == [("ie-a", False), ("ie-b", False)]


def test_unknown_route_is_empty(mounted):
    assert plan_query.programme_list("no_such_route", IntakeRef(term="winter", year=2027)).programmes == []
